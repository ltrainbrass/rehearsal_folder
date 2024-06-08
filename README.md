# rehearsal-folder

Initially created to prepare rehearsal Google Drive folders using the L Train or BMW agenda file.
- Pulls music folder links from a configured agenda file
- Copies files in each hyperlinked music folder that contain at least one of the configured keywords to an output rehearsal folder. Files are renamed (prefixed with `a.`, `b.`, etc.) to preserve song order specified in agenda

### Installation
- Install packages in requirements.txt with pip
- Follow the [Google Workspace API quickstart instructions](https://developers.google.com/drive/api/quickstart/python) up to the step of downloading a `credentials.json` file into your working folder
- Using `sample.ini` as a template, create an `ini` file to be passed to the script as a CLI argument.
  - The `ini` file should contain
    - The Google Drive id for the agenda file
    - A list of keywords that are used to determine which files to copy to an output folder
    - The Google Drive id of a folder in which the output folder should be created and the name to be used for the output folder
    - Optionally, logging levels for the functions in `main.py` and for `googleapiclient`

### Running the script
- Run using the following command if music folder links are to be read from a table within the agenda file:
```
python main.py <config ini path> --from-table=<1-indexed position of table>
```
- Otherwise, run the following command:
```
python main.py <config ini path>
```

A `token.json` file is created for using the Drive API. If the script is run without an existing `token.json` file, you will be prompted to sign into your Google Account and allow access to your account.

### TODO
- [ ] error handling for configuration
