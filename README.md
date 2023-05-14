# rehearsal-directory

Initially created to prepare rehearsal Google Drive folders using the L Train agenda file.
- Pulls music directory links from a configured agenda file
- Copies files in each hyperlinked music directory that contain at least one of the configured keywords to an output rehearsal directory. Files are renamed (prefixed with `a.`, `b.`, etc.) to preserve song order specified in agenda

### Installation
- Install packages in requirements.txt with pip
- Follow the [Google Workspace API quickstart instructions](https://developers.google.com/drive/api/quickstart/python) up to the step of downloading a `credentials.json` file into your working directory
- Using `sample.ini` as a template, create an `ini` file to be passed to the script as a CLI argument.
  - The `ini` file should contain
    - The Google Drive id for the agenda file
    - A list of keywords that are used to determine which files to copy to an output folder
    - The Google Drive id of a folder in which the output folder should be created and the name to be used for the output folder

### Running the script
- Run using the following command:
```
python main.py <config ini path>
```

A `token.json` file is created for using the Drive API. If the script is run without an existing `token.json` file, you will be prompted to sign into your Google Account and allow access to your account.

### TODO
- [ ] logging
- [ ] error handling for configuration
- [ ] code documentation
