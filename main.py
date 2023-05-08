from __future__ import print_function

import configparser
import os.path
import re

from argparse import ArgumentParser
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
        # TODO: exception?
        return build('drive', 'v3', credentials=creds)

    except HttpError as error:
        print(f'An error occurred: {error}')

def get_folders():
    folders = []

    soup = BeautifulSoup(html, 'html.parser')
    for link in soup.find_all('a', href=True):
        href = link['href']

        # Extract folder ids from links in HTML exported through Google Drive API.
        folder_id_pattern = "q=https://drive.google.com/.*/folders/(.*?)[&|?]"
        folder_id_matches = re.search(folder_id_pattern, href)
        
        if folder_id_matches is not None:
            id = folder_id_matches.group(1)
            folders.append({"id": id, "name": str(link.contents[0])})

    return folders

def get_folders_matching_files(folder_id):
    file_ids = []
    results = service.files().list(
        q = f"'{folder_id}' in parents and mimeType = 'application/pdf'",
        fields = "files(id, name)"
    ).execute()

    files = results['files']
    for file in files:
        for keyword in keywords:
            if keyword.casefold() in file['name'].casefold():
                file_ids.append((file['id'], file['name']))
                break
    return file_ids

def get_matching_files():
    file_ids = []
    for folder in folders:
        matching_file_ids = get_folders_matching_files(folder['id'])
        if not matching_file_ids:
            print(f"No matching files found for folder with id '{folder['name']}'")
            continue
        file_ids.append(matching_file_ids)
    return file_ids

def create_output_directory():
    results = service.files().list(
        q = f"'{output_folder_parent}' in parents " + 
            f"and name = '{output_folder_name}' " + 
            "and mimeType = 'application/vnd.google-apps.folder' " + 
            "and trashed = false",
        fields = "files(id, name)"
    ).execute()

    for result in results['files']:
        print (f"Deleting folder with name '{result['name']}' and id {result['id']}")
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

def copy_agenda_files():
    i = ord('a')
    for id_group in file_ids:
        for id_name_pair in id_group:
            service.files().copy(
                fileId = id_name_pair[0],
                body = {'name': chr(i) + ". " + id_name_pair[1],
                        'parents': [output_folder_id],
                }
            ).execute()
        i += 1

if __name__ == '__main__':
    parser = ArgumentParser(description='Process Google Docs export source_dir and write to dest_dir')
    parser.add_argument('config_ini_file', help="the file containing the configuration for the app", nargs=1)
    args = parser.parse_args()

    config_ini_file = args.config_ini_file
    config = configparser.RawConfigParser()
    config.read(config_ini_file)
    file_id = config['agenda_file']['id']

    service = create_service()
    html = service.files().export_media(fileId=file_id, mimeType='text/html').execute()
    folders = get_folders()
    
    keywords = [term.strip() for term in config['keywords']['keywords'].split(',')]
    file_ids = get_matching_files()

    output_folder_parent = config['output']['parent_id']
    output_folder_name = config['output']['folder_name']
    output_folder_id = create_output_directory()

    copy_agenda_files()
