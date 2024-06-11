import logging
import sys

from drive_io.drive_service import create_service
from drive_io.drive_operators import (
    AgendaFileReader,
    AgendaProcessor,
    KeywordFileSearcher,
    OutputFolderWriter
)
from argparse import ArgumentParser, Namespace
from configparser import NoOptionError, NoSectionError, RawConfigParser


def parse_arguments() -> Namespace:
    '''
    Configures an ArgumentParser and parsers command-line arguments

    Returns:
        Namespace: the parsed command arguments
    '''
    parser = ArgumentParser(
        description='Copies files from linked directories in a Google Drive '
        'agenda file to an output folder'
    )
    parser.add_argument(
        'config_ini_file',
        help='the file containing the configuration for the app',
        nargs=1
    )
    parser.add_argument(
        '--from-table',
        type=int,
        default=0,
        help='specifies the table index (1-indexed) from which to read '
        'directory links'
    )
    return parser.parse_args()


def main() -> None:
    '''
    Entry point of the script.

    - Parses command-line arguments
    - Reads a specified config ini file passed as a command-line 
        argument
    - Copies Google Drive files in folders linked within a specified
        Drive folder that contain a specified name keyword into a new
        Google Drive output folder
    '''
    args = parse_arguments()
    table_number = args.from_table

    config_ini_file = args.config_ini_file
    config = RawConfigParser()
    config.read(config_ini_file)

    logger = logging.getLogger('rehearsal_folder')

    try:
        rehearsal_folder_logging_level = (
            config['logging']['rehearsal_folder']
            if config.has_option('logging', 'rehearsal_folder')
            else logging.INFO
        )
        googleapiclient_logging_level = (
            config['logging']['googleapiclient']
            if config.has_option('logging', 'googleapiclient')
            else logging.WARNING
        )
        logging.basicConfig(level=rehearsal_folder_logging_level)
        google_logger = logging.getLogger('googleapiclient')
        google_logger.setLevel(googleapiclient_logging_level)
        agenda_file_id = config.get('agenda_file', 'id')
        keywords = config.get('keywords', 'keywords')
        output_folder_parent = config.get('output', 'parent_id')
        output_folder_name = config.get('output', 'folder_name')
    except (NoSectionError, NoOptionError) as e:
        logger.error(
            'Unable to extract required info from config ini file: %s',
            e
        )
        sys.exit(1)
    except ValueError as e:
        logger.error('Error while processing configuration: %s', e)
        sys.exit(1)

    try:
        service = create_service()
    except Exception as e:
        logger.error(
            ('Failed to create Resource for interacting with the Google Drive '
             'API: %s'),
            e)
        sys.exit(1)

    keywords = [keyword.strip() for keyword in keywords.split(',')]
    agenda_processor = AgendaProcessor(
        AgendaFileReader(service, logger, agenda_file_id, table_number),
        KeywordFileSearcher(service, logger, keywords),
        OutputFolderWriter(
            service,
            logger,
            output_folder_parent,
            output_folder_name
        )
    )
    agenda_processor.process()


if __name__ == '__main__':
    main()
