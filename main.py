import configparser
import logging 
import os.path
import re

from argparse import ArgumentParser
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger('rehearsal_directory') 

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive']

def create_service():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        return build('drive', 'v3', credentials=creds)

    except HttpError as error:
        logger.error('An error occurred: %s' % error)
        raise error

def get_folders(service, read_from_table, table_number, file_id):
    folders = []

    html = service.files().export_media(fileId=file_id, mimeType='text/html').execute()
    soup = BeautifulSoup(html, 'html.parser')
    if read_from_table:
        soup = soup.select_one('table:nth-of-type({})'.format(table_number))
        if soup is None:
            logger.error('Table #%d could not be found in the agenda file', table_number)
            return folders
        
    for link in soup.find_all('a', href=True):
        href = link['href']

        # Extract folder ids from links in HTML exported through Google Drive API.
        folder_id_pattern = 'q=https://drive.google.com/.*/folders/(.*?)[&|?]'
        folder_id_matches = re.search(folder_id_pattern, href)
        
        if folder_id_matches is not None:
            folders.append({'id': folder_id_matches.group(1), 'name': str(link.contents[0])})
        else:
            # Folder id could not be identified from link. Link may not be to a folder.
            logger.debug('No folder id found for \'%s\' - skipping link', link.text)

    return folders

def get_matching_files_in_folder(service, folder_id, keywords):
    file_ids = []
    results = service.files().list(
        q = f'\'{folder_id}\' in parents',
        fields = 'files(id, name, mimeType)'
    ).execute()

    files = results['files']
    pdf_files = [file for file in files if file['mimeType'] == 'application/pdf']
    if len(pdf_files) == 0:
        folders = [file for file in files if file['mimeType'] == 'application/vnd.google-apps.folder']
        if len(folders) != 0:
            # Find latest folder alphabetically, assuming that folder names are version names.
            last_folder = max(folders, key=lambda folder: folder['name'])
            return get_matching_files_in_folder(last_folder['id'], service, keywords)

    for file in pdf_files:
        for keyword in keywords:
            if keyword.casefold() in file['name'].casefold():
                file_ids.append((file['id'], file['name']))
                break
    return file_ids

def get_matching_files(service, folders, keywords):
    file_ids = []
    for folder in folders:
        matching_file_ids = get_matching_files_in_folder(service, folder['id'], keywords)
        if not matching_file_ids:
            logger.warning('No matching files found for folder with name=\'%s\', id=%s', 
                           folder['name'], folder['id'])
            continue
        file_ids.append(matching_file_ids)
    return file_ids

def create_output_directory(service, output_folder_parent, output_folder_name):
    results = service.files().list(
        q = f'\'{output_folder_parent}\' in parents ' + 
            f'and name = \'{output_folder_name}\' ' + 
            'and mimeType = \'application/vnd.google-apps.folder\' ' + 
            'and trashed = false',
        fields = 'files(id, name)'
    ).execute()

    for result in results['files']:
        logger.info('Deleting folder with name=%s, id=%s', result['name'], result['id'])
        service.files().delete(fileId=result['id']).execute()

    output_file = service.files().create(
        body = {
            'name': output_folder_name,
            'parents': [output_folder_parent],
            'mimeType': 'application/vnd.google-apps.folder'
            },
        fields='id'
    ).execute()

    return output_file['id']

def copy_agenda_files(service, file_ids, output_folder_id, output_folder_name):
    i = 0
    for id_group in file_ids:
        for id_name_pair in id_group:
            logger.debug('Copying \'%s\' to the output directory', id_name_pair[1])
            service.files().copy(
                fileId = id_name_pair[0],
                body = {'name': '%d. %s' % (i, id_name_pair[1]),
                        'parents': [output_folder_id]
                        }
            ).execute()
        i += 1
    logger.info('Successfully copied files to the \'%s\' directory', output_folder_name)

def parse_arguments():
    parser = ArgumentParser(description='Copies files from linked directories in a Google Drive agenda file to an output folder')
    parser.add_argument('config_ini_file', help='the file containing the configuration for the app', nargs=1)
    parser.add_argument('--from-table', type=int, default=0, help='specifies the table index (1-indexed) from which to read directory links')
    return parser.parse_args()

def main():
    args = parse_arguments()

    config_ini_file = args.config_ini_file
    config = configparser.RawConfigParser()
    config.read(config_ini_file)
    file_id = config['agenda_file']['id']
    read_from_table = args.from_table != 0
    table_number = args.from_table

    logging.basicConfig(level=config['logging']['rehearsal_directory'])
    google_logger = logging.getLogger('googleapiclient')
    google_logger.setLevel(config['logging']['googleapiclient'])

    service = create_service()
    folders = get_folders(service, read_from_table, table_number, file_id)
    if len(folders) != 0:
        keywords = [term.strip() for term in config['keywords']['keywords'].split(',')]
        file_ids = get_matching_files(service, folders, keywords)

        output_folder_parent = config['output']['parent_id']
        output_folder_name = config['output']['folder_name']
        
        output_folder_id = create_output_directory(service, output_folder_parent, output_folder_name)

        copy_agenda_files(service, file_ids, output_folder_id, output_folder_name)

if __name__ == '__main__':
    main()
