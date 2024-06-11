import re

from bs4 import BeautifulSoup
from googleapiclient.discovery import Resource
from logging import Logger
from typing import List


class AgendaFileReader:
    '''
    Class for reading the contents of an agenda file in 
    Google Drive
    '''

    def __init__(
        self,
        service: Resource,
        logger: Logger,
        agenda_file_id: str,
        table_number: int
    ) -> None:
        '''
        Constructs necessary attributes for the agenda file reader.

        Args:
            service (Resource): object with methods for interacting with
                the Google Drive API
            logger (Logging): logger instance to use for logging
            agenda_file_id (str): id of the agenda file to be read
            table_number (int): the index of the table (1-indexed) from 
                which to read folder links. 0 if links should not be 
                read from a specific table
        '''
        self.service = service
        self.logger = logger
        self.agenda_file_id = agenda_file_id
        self.table_number = table_number

    def get_linked_folders(self) -> List[str]:
        '''
        Returns a list of ids for folders linked in the Google Drive 
        file with the input agenda file id.

        Returns:
            List[str]: a list of linked Google Drive folder ids
            agenda_file_id (str): id of the agenda file to be read
            table_number (int): the index of the table (1-indexed) from 
                which to read folder links. 0 if links should not be 
                read from a specific table
        '''
        folders = []

        html = self.service.files().export_media(
            fileId=self.agenda_file_id,
            mimeType='text/html'
        ).execute()
        soup = BeautifulSoup(html, 'html.parser')
        if self.table_number != 0:
            soup = soup.select_one(
                'table:nth-of-type({})'.format(self.table_number)
            )
            if soup is None:
                self.logger.error(
                    'Table #%d could not be found in the agenda file',
                    self.table_number
                )
                return folders

        for link in soup.find_all('a', href=True):
            href = link['href']

            # Extract folder ids from links in HTML exported through
            # Google Drive API.
            folder_id_pattern = 'q=https://drive.google.com/.*/folders/(.*?)[&?]'
            folder_id_matches = re.search(folder_id_pattern, href)

            if folder_id_matches is not None:
                folders.append(
                    {
                        'id': folder_id_matches.group(1),
                        'name': str(link.contents[0])
                    }
                )
            else:
                # Folder id could not be identified from link. Link may
                # not be to a folder.
                self.logger.debug(
                    'No folder id found for \'%s\' - skipping link',
                    link.text
                )

        return folders


class KeywordFileSearcher:
    '''
    Class for searching for files in Google Drive with names containing
    keywords
    '''

    def __init__(
        self,
        service: Resource,
        logger: Logger,
        keywords: List[str]
    ) -> None:
        '''
        Constructs necessary attributes for the keyword file 
        searcher

        Args:
            service (Resource): object with methods for interacting with
                the Google Drive API
            logger (Logging): logger instance to use for logging
            keywords (List[str]): keywords to search for in file names
        '''
        self.service = service
        self.logger = logger
        self.keywords = keywords

    def find_matching_files_in_folder(
        self,
        folder_id: str,
    ) -> List[str]:
        '''
        Returns a list of ids for files within the input folder that
        have names with at least one keyword

        Args:
            folder_id (str): a Google Drive folder id

        Returns:
            List[str]: a list of ids for Google Drive files within the 
                specified folder that have names containing at least one
                keyword
        '''
        file_ids = []
        results = self.service.files().list(
            q=f'\'{folder_id}\' in parents',
            fields='files(id, name, mimeType)'
        ).execute()

        files = results['files']
        pdf_files = [file for file in files
                     if file['mimeType'] == 'application/pdf']
        if len(pdf_files) == 0:
            # Folder does not contain any direct file children. Check 
            # for subfolders.
            folders = [
                file for file in files
                if file['mimeType'] == 'application/vnd.google-apps.folder'
            ]
            if len(folders) != 0:
                # Find latest folder alphabetically, assuming that
                # folder names are version names.
                last_folder = max(
                    folders,
                    key=lambda folder: folder['name']
                )
                return self.find_matching_files_in_folder(last_folder['id'])

        for file in pdf_files:
            for keyword in self.keywords:
                if keyword.casefold() in file['name'].casefold():
                    file_ids.append((file['id'], file['name']))
                    break
        return file_ids

    def find_matching_files(
        self,
        folders: List[str]
    ) -> List[str]:
        '''
        Returns a list of ids for files from the input folders that have
        names with at least one of keyword

        Args:
            folders (List[str]): a list of Google Drive folder ids
        Returns:
            List[str]: a list of ids for Google Drive files from the 
                specified folders that have names containing at least 
                one keyword
        '''
        file_ids = []
        for folder in folders:
            matching_file_ids = self.find_matching_files_in_folder(
                folder['id']
            )
            if not matching_file_ids:
                self.logger.warning(
                    ('No matching files found in folder with name=\'%s\', '
                     'id=%s',),
                    folder['name'],
                    folder['id']
                )
                continue
            file_ids.append(matching_file_ids)
        return file_ids


class OutputFolderWriter:
    '''
    Class for creating and writing files to an output folder in 
    Google Drive
    '''

    def __init__(
        self,
        service: Resource,
        logger: Logger,
        output_folder_parent: str,
        output_folder_name: str
    ) -> None:
        '''
        Constructs necessary attributes for the output directory writer.

        Args:
            service (Resource): object with methods for interacting with
                the Google Drive API
            logger (Logging): logger instance to use for logging
            output_folder_parent (str): the id of the Google Drive 
                folder to create the output folder within
            output_folder_name (str): the name of the output folder to
                create
        '''
        self.service = service
        self.logger = logger
        self.output_folder_parent = output_folder_parent
        self.output_folder_name = output_folder_name

    def create_empty_output_folder(self) -> str:
        '''
        Creates a Google Drive folder with the output folder name within
        the output folder parent directory

        If such a folder already exists, it is overwritten

        Returns:
            str: the id of the created folder
        '''
        results = self.service.files().list(
            q=f'\'{self.output_folder_parent}\' in parents '
            f'and name = \'{self.output_folder_name}\' '
            'and mimeType = \'application/vnd.google-apps.folder\' '
            'and trashed = false',
            fields='files(id, name)'
        ).execute()

        for result in results['files']:
            self.logger.info(
                'Deleting folder with name=\'%s\', id=%s',
                result['name'],
                result['id']
            )
            self.service.files().delete(fileId=result['id']).execute()

        output_folder = self.service.files().create(
            body={
                'name': self.output_folder_name,
                'parents': [self.output_folder_parent],
                'mimeType': 'application/vnd.google-apps.folder'
            },
            fields='id'
        ).execute()

        return output_folder['id']

    def create_output_folder_with_files(
        self,
        file_ids: List[str]
    ) -> None:
        '''
        Creates an output directory containing copies of the specified
        Google Drive files

        Args:
            file_ids (List[str]): the ids of Google Drive files to copy
        '''
        output_folder_id = self.create_empty_output_folder()

        i = 0
        for id_group in file_ids:
            for id_name_pair in id_group:
                self.logger.debug(
                    'Copying \'%s\' to the output folder',
                    id_name_pair[1]
                )
                self.service.files().copy(
                    fileId=id_name_pair[0],
                    body={
                        'name': '%d. %s' % (i, id_name_pair[1]),
                        'parents': [output_folder_id]
                    }
                ).execute()
            i += 1
        self.logger.info(
            'Successfully copied files to the output folder with id=%s',
            output_folder_id
        )


class AgendaProcessor:
    '''
    Class to handle the processing of an agenda file in Google Drive
    and the creation of an output directory with relevant files based on
    the agenda
    '''

    def __init__(
        self,
        agenda_file_reader: AgendaFileReader,
        keyword_file_searcher: KeywordFileSearcher,
        output_folder_writer: OutputFolderWriter
    ) -> None:
        '''
        Constructs necessary attributes for the agenda processor.

        Args:
            agenda_file_reader (AgendaFileReader): handles reading of 
                an agenda file in Google Drive
            keyword_file_searcher (KeywordFileSearcher): handles 
                searching for files with names containing keywords
            output_folder_writer (OutputFolderWriter): handles creating
                and writing of files to an output folder
        '''
        self.agenda_file_reader = agenda_file_reader
        self.keyword_file_searcher = keyword_file_searcher
        self.output_folder_writer = output_folder_writer

    def process(self) -> None:
        '''
        Orchestrates the reading of an agenda file in Google Drive
        and the creation of an output directory with relevant files 
        based on the agenda
        '''
        folders = self.agenda_file_reader.get_linked_folders()

        if len(folders) != 0:
            file_ids = self.keyword_file_searcher.find_matching_files(folders)
            self.output_folder_writer.create_output_folder_with_files(file_ids)
