import argparse
import os
import fnmatch
import sys
import shutil # Added for directory clearing
import google.generativeai as genai

# Patterns to ignore during directory traversal
IGNORE_PATTERNS = [
    'node_modules',
    'package-lock.json',
    '.env',
    '.DS_Store',
    '.git',
    'public',
    '__pycache__',
    'generate_tests.py', # Ignore the script itself
    'output.txt',
    'postman.json',
    'seedDatabase.ts',
    '.next',
    'dist',
    'scripts',
    'venv',
    'robot_tests', # Ignore the default output directory
    '*.log',
    '*.xml', # Ignore report files etc.
    '*.png',
    '*.zip',
    '*.svg',
    '*.jpg',
    '.sauce',
    '.storybook',
    'test',
    '.backtracejsrc',
    '.dockerignore',
    '.dockerfile',
    'Dockerfile',
    'docker-compose.yml',
    'docker-compose.override.yml',
    'docker-compose.override.yaml',
    '.github',
    'README.md',
    'LICENSE.*',
    'Jenkinsfile',
    'Makefile',
    'Makefile.*',
    '__tests__',
    '__mocks__'

]

def should_ignore(path, ignore_patterns):
    """Check if a path matches any of the ignore patterns."""
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(os.path.basename(path), pattern):
            return True
        # Check if any part of the path matches
        parts = path.split(os.sep)
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False

def traverse_directory(root_dir, ignore_patterns):
    """
    Traverses the directory, reads file contents, and formats the structure.
    Excludes specified patterns.
    """
    formatted_output = ""
    for root, dirs, files in os.walk(root_dir, topdown=True):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), ignore_patterns)]

        for filename in files:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, root_dir)

            if should_ignore(file_path, ignore_patterns):
                continue

            formatted_output += f"--- File: {relative_path} ---\n"
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    formatted_output += content + "\n\n"
            except Exception as e:
                formatted_output += f"[Error reading file: {e}]\n\n"

    return formatted_output

def prepare_ai_prompt(directory_structure, chat_context=None):
    """Prepares the prompt for the Gemini AI."""
    prompt = f"""
Analyze the following web application structure and file contents:

{directory_structure}

Based on this analysis, generate the complete Robot Framework test suite using the Page Object Model (POM) structure and SeleniumLibrary.

Instructions:
1.  **File Generation:** Create the following files:
    *   Necessary Robot Framework resource files (`.robot` or `.py` for keywords/page objects).
    *   Robot Framework test suite files (`.robot`).
    *   A `requirements.txt` file listing *only* additional Python packages required besides `robotframework` and `robotframework-seleniumlibrary`. If none are needed, explicitly state this in the README.md instead of creating an empty file.
    *   A `README.md` file containing explanations, setup instructions (including installing requirements), and usage details (how to run the tests).
2.  **POM Structure:** Follow the Page Object Model strictly.
    *   Place page elements (locators) and keywords related to specific pages in their respective page object files (e.g., `pages/LoginPage.robot` or `pages/login_page.py`).
    *   Place generic keywords or setup/teardown logic in resource files (e.g., `resources/CommonKeywords.robot` or `resources/common_keywords.py`).
    *   Write test cases in separate suite files (e.g., `tests/LoginTests.robot`).
3.  **Robot Framework Content:**
    *   Use SeleniumLibrary for web interactions.
    *   **Do NOT include `Documentation` settings within the `.robot` files.** Put all explanations in the `README.md`.
    *   Ensure proper Robot Framework syntax and indentation.
4.  **Response Formatting:** Structure your response clearly, indicating the file path *relative to the output directory root* for each code block using the exact format `--- File: path/to/your/file ---`. Examples: `--- File: requirements.txt ---`, `--- File: pages/LoginPage.robot ---`, `--- File: tests/LoginTests.robot ---`, `--- File: README.md ---`.
5.  **Output:** Provide *only* the file markers and their corresponding content. Do not include any other explanatory text outside the `README.md` file content.

"""
    if chat_context:
        prompt += f"Additional Context:\n{chat_context}\n"

    prompt += "\nGenerate the Robot Framework code, requirements.txt (if needed), and README.md now:"
    return prompt

def interact_with_gemini(prompt, api_key):
    """Sends the prompt to Gemini AI and gets the response."""
    print("--- Configuring Gemini AI ---")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash-001') # Or choose another suitable model
        # model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25') # Or choose another suitable model
        print("--- Sending Prompt to AI ---")
        # print(prompt) # Optionally print the full prompt for debugging
        print("-----------------------------")
        response = model.generate_content(prompt)
        print("--- Received Response from AI ---")
        # print(response.text) # Optionally print the full response
        print("-------------------------------")
        return response.text
    except Exception as e:
        print(f"Error interacting with Gemini API: {e}", file=sys.stderr)
        # Consider more specific error handling based on potential API errors
        return None # Indicate failure

def parse_ai_response(response):
    """Parses the AI response to extract file contents and clean markdown fences."""
    files = {}
    current_path = None
    current_content = []

    # Use regex for more robust parsing of the delimiter
    import re
    # Matches lines like "--- File: path/to/file ---" or "--- File: path/to/file"
    file_delimiter_pattern = re.compile(r"^--- File:\s*(.*?)\s*(?:---)?$")
    # Regex to find markdown code fences (start and end)
    markdown_fence_pattern = re.compile(r"^\s*```(?:\w+)?\s*$") # Matches ``` or ```python etc.

    def clean_content(content_list):
        """Removes leading/trailing markdown code fences."""
        if not content_list:
            return ""
        # Make a copy to avoid modifying the original list during iteration
        cleaned_list = list(content_list)
        # Remove potential starting fence
        if cleaned_list and markdown_fence_pattern.match(cleaned_list[0]):
            cleaned_list.pop(0)
        # Remove potential ending fence (check again in case it was a single line)
        if cleaned_list and markdown_fence_pattern.match(cleaned_list[-1]):
            cleaned_list.pop(-1)
        return "\n".join(cleaned_list).strip()

    for line in response.strip().split('\n'):
        match = file_delimiter_pattern.match(line)
        if match:
            if current_path is not None: # Check if it's not the very first file
                # Clean the collected content before storing
                cleaned_content = clean_content(current_content)
                # Normalize path separators for consistency before storing
                normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
                files[normalized_path] = cleaned_content

            current_path = match.group(1).strip() # Extract the path
            current_content = [] # Reset content for the new file
            # print(f"DEBUG: Found file marker: {current_path}") # Debugging line
        elif current_path is not None: # Only append if we are currently inside a file block
            current_content.append(line)
        # else: # Optional: Log lines outside file blocks if needed
            # print(f"DEBUG: Ignoring line outside file block: {line}")

    if current_path is not None: # Add and clean the last file content
        cleaned_content = clean_content(current_content)
        # Normalize path separators for consistency before storing
        normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
        files[normalized_path] = cleaned_content

    return files


def store_test_files(files, output_dir="robot_tests", clear_output=False):
    """Stores the generated files in the specified directory."""

    if clear_output and os.path.exists(output_dir):
        try:
            shutil.rmtree(output_dir)
            print(f"Cleared existing output directory: {output_dir}")
        except OSError as e:
            print(f"Error clearing directory {output_dir}: {e}", file=sys.stderr)
            # Decide if you want to exit or continue
            # sys.exit(1)

    # Ensure the base output directory exists after potential clearing
    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")
        except OSError as e:
            print(f"Error creating directory {output_dir}: {e}", file=sys.stderr)
            sys.exit(1) # Exit if we can't create the main output dir

    # Use absolute path for output directory for reliable checks
    abs_output_dir = os.path.abspath(output_dir)

    for relative_file_path, content in files.items():
        # Basic validation: Ensure relative_file_path is not empty or just whitespace
        if not relative_file_path or relative_file_path.isspace():
            print(f"Warning: Skipping file with invalid relative path provided by AI: '{relative_file_path}'", file=sys.stderr)
            continue

        # Normalize the AI-provided relative path
        normalized_relative_path = os.path.normpath(relative_file_path)

        # Prevent paths trying to go 'up' (e.g., ../../etc/passwd)
        if ".." in normalized_relative_path.split(os.sep):
             print(f"Warning: Skipping potentially unsafe file path provided by AI: '{relative_file_path}'", file=sys.stderr)
             continue

        # Prevent absolute paths from AI response
        if os.path.isabs(normalized_relative_path):
             print(f"Warning: Skipping absolute file path provided by AI: '{relative_file_path}'", file=sys.stderr)
             continue

        # Construct the full, absolute path
        full_path = os.path.join(abs_output_dir, normalized_relative_path)
        full_path = os.path.abspath(full_path) # Resolve any potential symbolic links etc.

        # Security Check: Ensure the final path is truly within the output directory
        if not full_path.startswith(abs_output_dir + os.sep) and full_path != abs_output_dir:
            print(f"Warning: Skipping file path attempting to write outside output directory: '{relative_file_path}' resolved to '{full_path}' (outside '{abs_output_dir}')", file=sys.stderr)
            continue

        # Create subdirectories if they don't exist
        file_dir = os.path.dirname(full_path)
        # Check if file_dir is not empty and not the same as the output dir itself
        if file_dir and file_dir != abs_output_dir and not os.path.exists(file_dir):
            try:
                os.makedirs(file_dir)
                print(f"Created subdirectory: {file_dir}")
            except OSError as e:
                 print(f"Error creating subdirectory {file_dir} for {full_path}: {e}", file=sys.stderr)
                 continue # Skip this file if subdirectory creation fails

        # Write the file
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Wrote file: {full_path}")
        except Exception as e:
            print(f"Error writing file {full_path}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Generate Robot Framework tests using Gemini AI.")
    parser.add_argument("app_path", help="Path to the web application directory.")
    parser.add_argument("-c", "--context", help="Optional chat context for the AI.", default=None)
    parser.add_argument("-o", "--output", help="Output directory for generated tests.", default="robot_tests")
    parser.add_argument("--clear-output", action="store_true", help="Clear the output directory before writing new files.")

    args = parser.parse_args()

    # Get API Key
    # api_key = os.getenv("GEMINI_API_KEY")
    api_key="AIzaSyCAF0_vToE7aj3Zg9X6gN1qVD1_0KtpH58"
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1) # Exit if API key is missing

    if not os.path.isdir(args.app_path):
        print(f"Error: Path '{args.app_path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Traversing directory: {args.app_path}")
    directory_structure = traverse_directory(args.app_path, IGNORE_PATTERNS)

    if not directory_structure:
        print("No files found to process after applying ignore patterns.")
        return

    # print("--- Formatted Directory Structure ---")
    # print(directory_structure)
    # print("------------------------------------")

    print("Preparing AI prompt...")
    prompt = prepare_ai_prompt(directory_structure, args.context)

    print("Interacting with AI...")
    ai_response = interact_with_gemini(prompt, api_key)

    if ai_response is None:
        print("Failed to get response from AI. Exiting.", file=sys.stderr)
        sys.exit(1)

    print("Parsing AI response...")
    generated_files = parse_ai_response(ai_response)

    if not generated_files:
        print("AI did not return any files to store.")
        sys.exit(1)

    print(f"Storing generated files in '{args.output}'...")
    store_test_files(generated_files, args.output, args.clear_output)

    print("Test generation process complete.")

if __name__ == "__main__":
    main()