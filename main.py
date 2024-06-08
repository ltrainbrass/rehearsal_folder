import logging 
import os.path
import re
import sys

from argparse import ArgumentParser, Namespace
from bs4 import BeautifulSoup
from configparser import NoOptionError, NoSectionError, RawConfigParser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from typing import List

logger = logging.getLogger('rehearsal_folder') 

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive']

def create_service() -> Resource:
    """Creates a Resource for interacting with the Google Drive API

    Returns:
        Resource: object with methods for interacting with the Google Drive API
    """
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

def get_folders(service: Resource, file_id: str, table_number: int) -> List[str]:
    """Returns a list of ids for folders linked in the Google Drive file with the input id.

    Args:
        service (Resource): object with methods for interacting with the Google Drive API
        file_id (str): the id of the file to extract linked folder ids from
        table_number (int): the table index (1-indexed) from which to read directory links. 0 if links should not be read from a specific table

    Returns:
        List[str]: a list of linked Google Drive folder ids
    """
    folders = []

    html = service.files().export_media(fileId=file_id, mimeType='text/html').execute()
    soup = BeautifulSoup(html, 'html.parser')
    if table_number != 0:
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

def get_matching_files_in_folder(service: Resource, folder_id: str, keywords: List[str]) -> List[str]:
    """Returns a list of ids for files within the input folder that have names with at least one of the input keywords

    Args:
        service (Resource): object with methods for interacting with the Google Drive API
        folder_id (str): a Google Drive folder id
        keywords (List[str]): keywords to search for in names of files within the specified folder

    Returns:
        List[str]: a list of ids for Google Drive files within the specified folder that have names containing at least one keyword
    """
    file_ids = []
    results = service.files().list(
        q = f'\'{folder_id}\' in parents',
        fields = 'files(id, name, mimeType)'
    ).execute()

    files = results['files']
    pdf_files = [file for file in files if file['mimeType'] == 'application/pdf']
    if len(pdf_files) == 0:
        # Folder does not contain any direct file children. Check for subfolders.
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

def get_matching_files(service: Resource, folders: List[str], keywords: List[str]) -> List[str]:
    """Returns a list of ids for files from the input folders that have names with at least one of the input keywords

    Args:
        service (Resource): object with methods for interacting with the Google Drive API
        folders (List[str]): a list of Google Drive folder ids
        keywords (List[str]): keywords to search for in file names within the specified folders

    Returns:
        List[str]: a list of ids for Google Drive files from the specified folders that have names containing at least one keyword
    """
    file_ids = []
    for folder in folders:
        matching_file_ids = get_matching_files_in_folder(service, folder['id'], keywords)
        if not matching_file_ids:
            logger.warning('No matching files found for folder with name=\'%s\', id=%s', 
                           folder['name'], folder['id'])
            continue
        file_ids.append(matching_file_ids)
    return file_ids

def create_output_folder(service: Resource, output_folder_parent: str, output_folder_name: str) -> str:
    """Creates a new Google Drive folder with the specified name within the specified existing Drive folder

    Args:
        service (Resource): object with methods for interacting with the Google Drive API
        output_folder_parent (str): the id of the Google Drive folder to create the new folder within
        output_folder_name (str): the name of the new folder to create

    Returns:
        str: the id of the created folder
    """
    results = service.files().list(
        q = f'\'{output_folder_parent}\' in parents ' + 
            f'and name = \'{output_folder_name}\' ' + 
            'and mimeType = \'application/vnd.google-apps.folder\' ' + 
            'and trashed = false',
        fields = 'files(id, name)'
    ).execute()

    for result in results['files']:
        logger.info('Deleting folder with name=\'%s\', id=%s', result['name'], result['id'])
        service.files().delete(fileId=result['id']).execute()

    output_folder = service.files().create(
        body = {
            'name': output_folder_name,
            'parents': [output_folder_parent],
            'mimeType': 'application/vnd.google-apps.folder'
            },
        fields='id'
    ).execute()

    return output_folder['id']

def copy_files_to_folder(service: Resource, file_ids: List[str], output_folder_id: str, output_folder_name: str) -> None:
    """Creates copies of the specified Google Drive files in the specified output directory.

    Args:
        service (Resource): object with methods for interacting with the Google Drive API
        file_ids (List[str]): the ids of Google Drive files to copy
        output_folder_id (str): the id of the Google Drive folder to copy files to
        output_folder_name (str): the name of the Google Drive folder to copy files to
    """
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

def parse_arguments() -> Namespace:
    """Configures an ArgumentParser and parsers command-line arguments

    Returns:
        Namespace: the parsed command arguments
    """
    parser = ArgumentParser(description='Copies files from linked directories in a Google Drive agenda file to an output folder')
    parser.add_argument('config_ini_file', help='the file containing the configuration for the app', nargs=1)
    parser.add_argument('--from-table', type=int, default=0, help='specifies the table index (1-indexed) from which to read directory links')
    return parser.parse_args()

def main() -> None:
    """Entry point of the script.

    - Parses command-line arguments
    - Reads a specified config ini file passed as a command-line argument
    - Copies Google Drive files in folders linked within a specified Drive folder that contain a specified name keyword into a new Google Drive output folder
    """
    args = parse_arguments()
    table_number = args.from_table

    config_ini_file = args.config_ini_file
    config = RawConfigParser()
    config.read(config_ini_file)

    try:
        rehearsal_folder_logging_level = (config['logging']['rehearsal_folder'] 
                                         if config.has_option('logging', 'rehearsal_folder') 
                                         else logging.INFO)
        googleapiclient_logging_level = (config['logging']['googleapiclient']
                                     if config.has_option('logging', 'googleapiclient') 
                                     else logging.WARNING)
        logging.basicConfig(level=rehearsal_folder_logging_level)
        google_logger = logging.getLogger('googleapiclient')
        google_logger.setLevel(googleapiclient_logging_level)
        file_id = config.get('agenda_file', 'id')
        keywords = config.get('keywords', 'keywords')
        output_folder_parent = config.get('output', 'parent_id')
        output_folder_name = config.get('output', 'folder_name')
    except (NoSectionError, NoOptionError) as e:
        logger.error('Unable to extract required info from config ini file: %s' % e)
        sys.exit(1)
    except ValueError as e:
        logger.error('Error while processing configuration: %s' % e)
        sys.exit(1)

    service = create_service()
    folders = get_folders(service, file_id, table_number)
    if len(folders) != 0:
        keywords = [keyword.strip() for keyword in keywords.split(',')]
        file_ids = get_matching_files(service, folders, keywords)
        output_folder_id = create_output_folder(service, output_folder_parent, output_folder_name)
        copy_files_to_folder(service, file_ids, output_folder_id, output_folder_name)

if __name__ == '__main__':
    main()
