# Contribution Guide

## Creating a New Handler

1. **Create a New Python Class**: 
   - Navigate to the `/src/handlers` directory.
   - Create a new Python file for your handler.
   - Define a new class that will handle specific commands or messages.

2. **Implement the Handler Logic**: 
   - Implement the necessary methods to process updates and interact with the Telegram API.

3. **Register the Handler**: 
   - Open `main.py`.
   - Import your new handler class.
   - Add it to the Telegram application using the appropriate handler method (e.g., `CommandHandler`, `MessageHandler`).

## Creating a New Spam Filter

1. **Create a New Folder**: 
   - Navigate to the `src/handlers/spam_filters` directory.
   - Create a new folder for your spam filter.

2. **Create a Python Class**: 
   - Inside the new folder, create a Python file for your filter.
   - Define a class that extends `SpamFilter` or `HTTPJsonSpamFilter` if HTTP requests are needed.

3. **Implement the Filter Logic**: 
   - Override the `_is_spam` method to define the spam detection logic.
   - Implement any additional methods required for your filter.

4. **Integrate the Filter**: 
   - Open `FilterFactory.py`.
   - Add your new filter to the filter chain in the `get_default_chain` method.

5. **Register the Filter**: 
   - Ensure your filter is included in the spam filter chain in `main.py`.

## I want a new language for OCR (tesseract). How can I add it?

1. **Find the Language Pack**: 
   - Use the `tesseract --list-langs` command to list the available language packs or visit [this link](https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html)

2. **[FOR DOCKER ONLY] Modify the Dockerfile**:
   - Open the `Dockerfile` in the root directory.
   - Add the necessary package for the new language pack (e.g., `tesseract-ocr-<LANG_CODE>`). 
   Example: `RUN apt-get install -y tesseract-ocr-eng`

3. **[FOR LOCAL INSTALLATION] Install the Language Pack**:
   - Use the package manager of your choice to install the language pack (e.g., `apt-get install tesseract-ocr-<LANG_CODE>`).


By following these guidelines, you can extend the functionality of the B4CKSP4CE Telegram Antispam Bot with custom handlers and filters.

