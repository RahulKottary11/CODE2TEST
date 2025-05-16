import argparse
import os
import fnmatch
import sys
import shutil
import json
import re
import google.generativeai as genai

# --- Configuration ---

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

# --- Helper Functions ---

def should_ignore(path, ignore_patterns):
    """Check if a path matches any of the ignore patterns."""
    base_name = os.path.basename(path)
    # Check base name first
    if any(fnmatch.fnmatch(base_name, pattern) for pattern in ignore_patterns):
        return True
    # Check if any part of the path matches (for directories)
    parts = path.split(os.sep)
    if any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in ignore_patterns):
         # Be careful with directory patterns - ensure it's not just a file matching a dir pattern
         if os.path.isdir(path) or base_name == part: # Check if it's the directory itself or a file matching a dir pattern exactly
            return True
    return False

def traverse_directory(root_dir, ignore_patterns):
    """
    Traverses the directory, reads file contents, and formats the structure.
    Excludes specified patterns.
    """
    formatted_output = ""
    print(f"Starting traversal from: {os.path.abspath(root_dir)}")
    print(f"Ignoring patterns: {ignore_patterns}")

    # Normalize root_dir path
    root_dir = os.path.abspath(root_dir)

    for root, dirs, files in os.walk(root_dir, topdown=True):
        # Filter directories based on ignore patterns
        dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), ignore_patterns)]

        # Process files
        for filename in files:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, root_dir)

            if should_ignore(file_path, ignore_patterns):
                # print(f"Ignoring file: {relative_path}")
                continue

            # print(f"Processing file: {relative_path}")
            formatted_output += f"--- File: {relative_path} ---\n"
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    formatted_output += content + "\n\n"
            except Exception as e:
                formatted_output += f"[Error reading file {relative_path}: {e}]\n\n"

    if not formatted_output:
        print("Warning: No files found or read after applying ignore patterns.")
    return formatted_output

# --- Agent 1: Analysis and Planning ---

def prepare_analysis_prompt(directory_structure, user_context=None):
    """Prepares the prompt for Agent 1 (Analysis), incorporating user context."""
    context_injection = ""
    if user_context:
        context_injection = f"""
IMPORTANT User Context/Overrides:
---
{user_context}
---
Please take the above context into account during your analysis and planning. It may contain specific instructions, overrides, or focus areas.
"""

    prompt = f"""
Analyze the following web application source code and structure:

{directory_structure}
{context_injection}
Based on this analysis (and considering the user context if provided), generate a structured JSON plan for creating Robot Framework tests using the Page Object Model (POM).

Instructions for JSON Output:
1.  **Root Object:** The output MUST be a single JSON object. Do NOT include any text before or after the JSON object. Do not use markdown code fences (```json ... ```).
2.  **`application_summary` (String):** A brief description of the application's purpose.
3.  **`folder_structure` (Object):** Define the exact folder structure to use:
    *   `pages_directory` (String): Directory for page objects (e.g., "pages")
    *   `keywords_directory` (String): Directory for keyword files (e.g., "keywords")
    *   `tests_directory` (String): Directory for test files (e.g., "tests")
    *   `resources_directory` (String): Directory for resource files (e.g., "resources")
    *   `variables_directory` (String): Directory for variable files (e.g., "variables")
4.  **`pages` (Array of Objects):** List the distinct pages identified. Each page object should have:
    *   `name` (String): A suitable CamelCase name for the page object (e.g., "LoginPage", "ProductDetailsPage").
    *   `path` (String): The suggested relative path for the page object file (MUST be in the pages directory, e.g., "pages/LoginPage.robot").
    *   `elements` (Array of Objects): Key UI elements on the page. Each element object should have:
        *   `name` (String): A descriptive name for the element (e.g., "Username Field", "AddToCart Button").
        *   `potential_locators` (Array of Strings): Suggest 1-3 potential Selenium locators (e.g., "id=username", "css=.login-form input[name='password']", "xpath=//button[contains(text(), 'Submit')]"). Prioritize robust locators like IDs or unique names/attributes.
5.  **`keywords` (Array of Objects):** Define keywords that implement page actions. Each keyword object should have:
    *   `name` (String): A descriptive name for the keyword (e.g., "Input Username", "Click Login Button")
    *   `path` (String): The relative path for the keyword file (MUST be in the keywords directory, e.g., "keywords/LoginKeywords.robot")
    *   `implementation` (String): Brief pseudo-code or description of how this keyword would be implemented
    *   `associated_page` (String): The page this keyword interacts with (must match a page name defined above)
    *   `elements_used` (Array of Strings): References to elements used in this keyword (must exactly match element names defined above)
6.  **`test_scenarios` (Array of Objects):** Describe potential test cases. Each scenario object should have:
    *   `name` (String): A descriptive name for the test case (e.g., "Valid Login", "Add Item to Cart").
    *   `suite_path` (String): The suggested relative path for the test suite file where this test might reside (MUST be in the tests directory, e.g., "tests/LoginTests.robot").
    *   `steps` (Array of Objects): A sequence of keywords describing the test flow. Each step object should have:
        *   `keyword` (String): The keyword to call (must exactly match a keyword name)
        *   `args` (Array of Strings): Any arguments to pass to the keyword, if applicable
7.  **`resources` (Array of Objects):** Define resource files containing common keywords or variables. Each resource object should have:
    *   `name` (String): A descriptive name for the resource file (e.g., "CommonResources", "BrowserSetup")
    *   `path` (String): The suggested relative path for the resource file (MUST be in the resources directory, e.g., "resources/CommonResources.robot")
    *   `purpose` (String): Brief description of what this resource file provides
8.  **`required_libraries` (Array of Strings):** List any Robot Framework libraries likely needed besides the standard `BuiltIn` and `SeleniumLibrary` (e.g., "DataDriver", "RequestsLibrary"). If none, provide an empty array `[]`.
9.  **`setup_instructions_notes` (String):** Brief notes for setting up the test environment (e.g., "Requires Chrome WebDriver", "Needs environment variables X and Y").

Generate ONLY the JSON object representing this plan. Be extremely precise about naming consistency between elements, keywords, and test steps to ensure proper traceability.
"""
    return prompt

def parse_analysis_response(response_text):
    """Parses the JSON response from Agent 1, handling markdown formatting while preserving code examples."""
    print("--- Parsing Analysis Response ---")
    try:
        # First attempt: Try to parse the raw response directly
        # This works if the response is already clean JSON
        try:
            analysis_plan = json.loads(response_text.strip())
            print("Successfully parsed analysis plan directly (JSON).")
            return analysis_plan
        except json.JSONDecodeError:
            # Direct parsing failed, try more sophisticated approaches
            pass
            
        # Second attempt: Look for a JSON block wrapped in triple backticks
        # This pattern finds content between ```json and ``` markers
        json_block_pattern = re.compile(r"```json\s*([\s\S]*?)\s*```")
        match = json_block_pattern.search(response_text)
        
        if match:
            # Found a json code block, try parsing just that content
            json_content = match.group(1).strip()
            try:
                analysis_plan = json.loads(json_content)
                print("Successfully parsed analysis plan from markdown code block.")
                return analysis_plan
            except json.JSONDecodeError:
                # JSON block wasn't valid, continue to next approach
                pass
                
        # Third attempt: Try to find anything that looks like a complete JSON object
        # Look for content starting with { and ending with }
        json_pattern = re.compile(r"(\{[\s\S]*\})")
        match = json_pattern.search(response_text)
        
        if match:
            possible_json = match.group(1)
            try:
                analysis_plan = json.loads(possible_json)
                print("Successfully parsed analysis plan from extracted JSON object.")
                return analysis_plan
            except json.JSONDecodeError:
                # Not valid JSON, will proceed to final attempt
                pass
                
        # Final attempt: Try a much more conservative approach
        # Only remove outermost markdown code block markers if they appear to wrap the entire content
        if response_text.strip().startswith("```") and response_text.strip().endswith("```"):
            # Remove only the first ``` and last ```
            cleaned_text = re.sub(r"^```(?:json)?\s*([\s\S]*)\s*```$", r"\1", response_text.strip())
            try:
                analysis_plan = json.loads(cleaned_text)
                print("Successfully parsed analysis plan after removing outer markdown markers.")
                return analysis_plan
            except json.JSONDecodeError as e:
                print(f"All JSON parsing attempts failed: {e}")
                
        print("Warning: Could not parse any valid JSON from the response.")
        print("--- Raw Response Text (Agent 1) ---")
        print(response_text[:500] + "..." if len(response_text) > 500 else response_text)
        print("------------------------------------")
        return None
        
    except Exception as e:
        print(f"Error parsing analysis response: {e}", file=sys.stderr)
        print("--- Raw Response Text (Agent 1) ---")
        print(response_text[:500] + "..." if len(response_text) > 500 else response_text)
        print("------------------------------------")
        return None

# --- Agent 2: Code Generation ---

def prepare_generation_prompt(analysis_plan_json, user_context=None):
    """Prepares the prompt for Agent 2 (Code Generation), incorporating user context."""
    plan_str = json.dumps(analysis_plan_json, indent=2)
    context_injection = ""
    if user_context:
        context_injection = f"""
IMPORTANT User Context/Overrides:
---
{user_context}
---
Please take the above context into account when generating the code. It may contain specific instructions, style preferences, or details not fully captured in the JSON plan. Apply these overrides where applicable.
"""

    prompt = f"""
Based on the following JSON analysis plan:

```json
{plan_str}
```

{context_injection}
Generate the complete Robot Framework test suite using a strict Page Object Model (POM) structure and SeleniumLibrary, following the plan and considering the user context.

IMPORTANT: Follow this strict POM structure:
1. **Page Objects** (in the pages directory): ONLY contain element locators and page-specific variables
2. **Keywords** (in the keywords directory): Implement all actions and operations, using elements from page objects
3. **Test Cases** (in the tests directory): ONLY call keywords from keyword files, never directly access page elements
4. **Resources** (in the resources directory): Common setup, teardown, and utility code
5. **Variables** (if needed, in variables directory): Global variables and configuration

Instructions:
1. **File Generation:** Create files in the exact directories specified in the `folder_structure` section:
   * Page objects MUST go in the pages directory
   * Keywords MUST go in the keywords directory
   * Tests MUST go in the tests directory 
   * Common resources MUST go in the resources directory

2. **Imports:** Each file MUST include the correct imports:
   * Page files import SeleniumLibrary and any needed resources
   * Keyword files import their associated page objects
   * Test files import keyword files they use
   * Set explicit relative paths in imports using the `../` notation as needed

3. **Elements vs. Keywords:**
   * Page files ONLY define element locators as variables - NO keyword implementations
   * All action implementations MUST be in keyword files, not page files
   * Each keyword file MUST correctly reference elements from its associated page file

4. **Variables:**
   * Use standard Robot Framework variable conventions
   * All locators MUST be defined as variables, e.g., `${{USERNAME_FIELD}}=    id=username`
   * NO hardcoded locators in keyword implementations

5. **Resource Files:**
   * Create common resource files for setup/teardown and utility functions
   * Implement proper Suite Setup/Teardown in test files that handle browser instances

6. **Output Files Format:**
   * `requirements.txt`: Python packages needed beyond robotframework and robotframework-seleniumlibrary
   * `README.md`: Explanation, setup instructions, and usage details
   * Robot files with proper Robot Framework syntax and structure

7. **Response Formatting:** Mark each file with the exact path, e.g., `--- File: pages/LoginPage.robot ---`

Generate the complete Robot Framework code now based strictly on the provided JSON plan and properly separated POM structure.
"""
    return prompt

def parse_generation_response(response):
    """Parses the AI response from Agent 2 to extract file contents, handling markdown formatting properly."""
    print("--- Parsing Generation Response ---")
    files = {}
    current_path = None
    current_content = []
    in_code_block = False
    code_block_language = None

    # Use regex for more robust parsing of the delimiter
    # Matches lines like "--- File: path/to/file ---" or "--- File: path/to/file"
    file_delimiter_pattern = re.compile(r"^--- File:\s*(.*?)\s*(?:---)?$")
    # Pattern to detect code block markers
    code_block_pattern = re.compile(r"^```(\w*)$")

    def process_content(content_list, is_markdown_file=False):
        """Process content based on file type and code block status."""
        if not content_list:
            return ""
            
        # Skip processing if this is a markdown file and we want to preserve its formatting
        if is_markdown_file:
            return "\n".join(content_list)
            
        # For non-markdown files, clean up any code block formatting
        result = []
        skip_next_line = False
        in_internal_block = False
        
        for i, line in enumerate(content_list):
            # Skip this line if flagged by previous iteration
            if skip_next_line:
                skip_next_line = False
                continue
                
            # Check for code block markers
            code_match = code_block_pattern.match(line.strip())
            if code_match:
                # Toggle code block state
                in_internal_block = not in_internal_block
                # Skip this line
                continue
                
            # Add normal lines
            result.append(line)
            
        return "\n".join(result)

    for line in response.strip().split('\n'):
        # Check if this is a file delimiter line
        file_match = file_delimiter_pattern.match(line)
        if file_match:
            # Save previous file content if there was one
            if current_path is not None:
                # Check if this is likely a markdown file
                is_markdown_file = current_path.lower().endswith(('.md', '.markdown'))
                # Process content according to file type
                processed_content = process_content(current_content, is_markdown_file)
                normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
                files[normalized_path] = processed_content

            # Start new file
            current_path = file_match.group(1).strip()
            current_content = []
            in_code_block = False
        elif current_path is not None:
            # Check for code block markers - only for tracking, actual removal happens in process_content
            code_match = code_block_pattern.match(line.strip())
            if code_match:
                code_block_language = code_match.group(1)
                in_code_block = not in_code_block
                
            # Always add the line - filtering happens during processing
            current_content.append(line)

    # Don't forget the last file
    if current_path is not None:
        is_markdown_file = current_path.lower().endswith(('.md', '.markdown'))
        processed_content = process_content(current_content, is_markdown_file)
        normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
        files[normalized_path] = processed_content

    if not files:
        print("Warning: No files extracted from response.")
    else:
        print(f"Extracted {len(files)} files from response.")
    return files

# --- Agent 3: Validation and Enhancement ---

def prepare_validation_prompt(analysis_plan_json, generated_files, user_context=None):
    """Prepares the prompt for Agent 3 (Validation), incorporating user context."""
    plan_str = json.dumps(analysis_plan_json, indent=2)
    
    # Format the generated files for inclusion in the prompt
    files_str = ""
    for file_path, content in generated_files.items():
        files_str += f"\n--- File: {file_path} ---\n{content}\n"
    
    context_injection = ""
    if user_context:
        context_injection = f"""
IMPORTANT User Context/Overrides:
---
{user_context}
---
Please take the above context into account during your validation. It may contain specific instructions or focus areas.
"""

    prompt = f"""
As a Robot Framework expert specializing in Page Object Model (POM) implementation, perform a rigorous validation of the following generated test files:

1. The original analysis plan:
```json
{plan_str}
```

2. The generated test files:
{files_str}

{context_injection}

Your task is to conduct an extremely thorough validation of the code against strict POM standards and Robot Framework best practices. You MUST check for and fix all of the following issues:

1. **Critical POM Structure Validation:**
   * VERIFY all page files ONLY contain element locators and variables, NOT keyword implementations
   * VERIFY all keywords are implemented in the keywords directory, NOT in page files
   * VERIFY test files ONLY call keywords from keyword files, never directly interact with page elements
   * VERIFY directory structure is correct with pages, keywords, tests, and resources properly separated

2. **File Organization:**
   * VERIFY each file is in its correct directory as specified in the analysis plan
   * VERIFY imports use correct relative paths between files (../pages/, ../keywords/, etc.)
   * VERIFY no implementation logic is in the wrong file type

3. **Element and Keyword Validation:**
   * VERIFY all elements mentioned in the analysis plan are properly defined as variables
   * VERIFY all keywords mentioned in test cases are properly implemented
   * VERIFY no hardcoded locators in keyword implementations

4. **Import and Resource Validation:**
   * VERIFY all necessary imports are present in each file
   * VERIFY correct library imports (SeleniumLibrary, etc.) in appropriate files
   * VERIFY resource files are imported where needed with correct paths

5. **Robot Framework Syntax:**
   * VERIFY proper Robot Framework syntax, indentation, and structure
   * VERIFY proper variable naming conventions
   * VERIFY proper keyword naming and arguments

6. **Test Completeness:**
   * VERIFY test cases include all steps from the analysis plan
   * VERIFY proper setup and teardown implementation
   * VERIFY all required libraries are properly used

7. **Critical Fix Requirements:**
   * CREATE missing files if needed to complete the POM structure
   * RELOCATE code to correct files if found in wrong locations
   * RESOLVE import issues with correct paths
   * IMPLEMENT missing keywords required by tests
   * SPLIT files that inappropriately mix different POM concerns

Instructions for your response:
1. First, provide a detailed JSON validation report with these fields:
   * `issues_found` (boolean): Whether issues were found
   * `critical_pom_violations` (array): List of violations of POM structure
   * `missing_implementations` (array): Missing keywords or elements
   * `incorrect_file_organization` (array): Code in wrong files/directories
   * `syntax_errors` (array): Robot Framework syntax issues
   * `import_errors` (array): Missing or incorrect imports
   * `recommended_fixes` (array): Specific fixes needed

2. Then, provide ALL fixed files, regardless of whether they needed changes or not:
   * Include the full file path with the format `--- File: path/to/file ---`
   * Provide the COMPLETE fixed content for the file
   * If creating new files, mark them as `--- File: path/to/new/file (NEW) ---`

Review the code extremely carefully, focusing especially on proper POM structure separation between pages, keywords, and tests.
"""
    return prompt


def parse_validation_response(response):
    """Parses the AI response from Agent 3 to extract validation report and fixed files, handling markdown formatting properly."""
    print("--- Parsing Validation Response ---")
    
    # Extract the JSON validation report
    validation_report = None
    
    # More robust JSON pattern to handle triple backticks with or without language indicator
    json_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")
    json_match = json_pattern.search(response)
    
    if json_match:
        try:
            json_text = json_match.group(1).strip()
            validation_report = json.loads(json_text)
            print("Successfully parsed validation report (JSON).")
        except json.JSONDecodeError as e:
            print(f"Error: Failed to decode JSON validation report: {e}", file=sys.stderr)
            # Fallback: try to find raw JSON object
            try:
                json_obj_pattern = re.compile(r"(\{[\s\S]*\})")
                json_obj_match = json_obj_pattern.search(response)
                if json_obj_match:
                    validation_report = json.loads(json_obj_match.group(1))
                    print("Successfully parsed validation report using fallback method.")
            except:
                print("All validation report parsing methods failed.")
    else:
        print("Warning: No JSON validation report found in Agent 3's response.")
    
    # Extract fixed files using improved parsing logic
    files = {}
    current_path = None
    current_content = []
    in_code_block = False
    
    # Find where the file section starts (after the JSON validation report)
    file_section = response
    if json_match:
        # Get everything after the first JSON block
        json_end_pos = json_match.end()
        if json_end_pos < len(response):
            file_section = response[json_end_pos:]
    
    file_delimiter_pattern = re.compile(r"^--- File:\s*(.*?)\s*(?:---)?(?:\s*\(NEW\))?$")
    code_block_pattern = re.compile(r"^```(\w*)$")
    
    def process_content(content_list, is_markdown_file=False):
        """Process content based on file type."""
        if not content_list:
            return ""
            
        # Preserve formatting for markdown files
        if is_markdown_file:
            return "\n".join(content_list)
            
        # For non-markdown files, clean up code block formatting
        result = []
        skip_next_line = False
        in_internal_block = False
        
        for i, line in enumerate(content_list):
            # Skip this line if flagged by previous iteration
            if skip_next_line:
                skip_next_line = False
                continue
                
            # Check for code block markers
            code_match = code_block_pattern.match(line.strip())
            if code_match:
                # Toggle code block state
                in_internal_block = not in_internal_block
                # Skip this line
                continue
                
            # Add normal lines
            result.append(line)
            
        return "\n".join(result)
    
    for line in file_section.strip().split('\n'):
        # Check if this is a file delimiter
        file_match = file_delimiter_pattern.match(line)
        if file_match:
            # Save previous file if there was one
            if current_path is not None:
                is_markdown_file = current_path.lower().endswith(('.md', '.markdown'))
                processed_content = process_content(current_content, is_markdown_file)
                normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
                files[normalized_path] = processed_content
            
            # Start new file
            current_path = file_match.group(1).strip()
            current_content = []
            in_code_block = False
        elif current_path is not None:
            # Track code blocks for better processing
            code_match = code_block_pattern.match(line.strip())
            if code_match:
                in_code_block = not in_code_block
                
            # Always add line - filtering happens during processing
            current_content.append(line)
    
    # Don't forget the last file
    if current_path is not None:
        is_markdown_file = current_path.lower().endswith(('.md', '.markdown'))
        processed_content = process_content(current_content, is_markdown_file)
        normalized_path = current_path.replace('/', os.sep).replace('\\', os.sep)
        files[normalized_path] = processed_content
    
    return validation_report, files

# --- LLM Interaction ---

def interact_with_gemini(prompt, api_key, agent_name="Agent"):
    """Sends the prompt to Gemini AI and gets the response."""
    print(f"--- Configuring Gemini AI for {agent_name} ---")
    try:
        # Consider configuring once if API key doesn't change
        genai.configure(api_key=api_key)
        # Select appropriate model based on task complexity
        if agent_name == "Agent 2 (Generation)":
            # Use more capable model for validation which requires deeper analysis
            model = genai.GenerativeModel('gemini-2.0-flash-001')
            # model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25') # Or choose another suitable model
        else:
            # Use faster model for other tasks
            model = genai.GenerativeModel('gemini-2.0-flash-001')
            # model = genai.GenerativeModel('gemini-2.5-pro-exp-03-25') # Or choose another suitable model

        
        print(f"--- Sending Prompt to {agent_name} ---")
        response = model.generate_content(prompt)
        print(f"--- Received Response from {agent_name} ---")
        
        # Add basic safety check if response has feedback
        if response.prompt_feedback and response.prompt_feedback.block_reason:
             print(f"Warning: Prompt blocked by API for {agent_name}. Reason: {response.prompt_feedback.block_reason}", file=sys.stderr)
             return None
        # Check if response has candidates
        if not response.candidates:
             print(f"Warning: No content candidates received from {agent_name}.", file=sys.stderr)
             return None

        # Assuming the first candidate has the content
        if response.candidates[0].content and response.candidates[0].content.parts:
             return response.candidates[0].content.parts[0].text
        else:
             print(f"Warning: Response from {agent_name} has no text content.", file=sys.stderr)
             return ""

    except Exception as e:
        print(f"Error interacting with Gemini API for {agent_name}: {e}", file=sys.stderr)
        return None

# --- File Storage ---

def store_test_files(files, output_dir="robot_tests", clear_output=False):
    """Stores the generated files in the specified directory."""
    print(f"--- Storing Files in {output_dir} ---")

    abs_output_dir = os.path.abspath(output_dir)

    if clear_output and os.path.exists(abs_output_dir):
        try:
            shutil.rmtree(abs_output_dir)
            print(f"Cleared existing output directory: {abs_output_dir}")
        except OSError as e:
            print(f"Error clearing directory {abs_output_dir}: {e}", file=sys.stderr)

    # Ensure the base output directory exists after potential clearing
    if not os.path.exists(abs_output_dir):
        try:
            os.makedirs(abs_output_dir)
            print(f"Created output directory: {abs_output_dir}")
        except OSError as e:
            print(f"Error creating directory {abs_output_dir}: {e}", file=sys.stderr)
            sys.exit(1) # Exit if we can't create the main output dir

    files_written = 0
    for relative_file_path, content in files.items():
        if not relative_file_path or relative_file_path.isspace():
            print(f"Warning: Skipping file with invalid relative path provided by AI: '{relative_file_path}'", file=sys.stderr)
            continue

        normalized_relative_path = os.path.normpath(relative_file_path)

        if ".." in normalized_relative_path.split(os.sep):
             print(f"Warning: Skipping potentially unsafe file path provided by AI: '{relative_file_path}'", file=sys.stderr)
             continue

        if os.path.isabs(normalized_relative_path):
             print(f"Warning: Skipping absolute file path provided by AI: '{relative_file_path}'", file=sys.stderr)
             continue

        full_path = os.path.join(abs_output_dir, normalized_relative_path)
        full_path = os.path.abspath(full_path)

        # Security Check: Ensure the final path is truly within the output directory
        # Allow writing to the output directory itself (e.g., README.md)
        if not full_path.startswith(abs_output_dir + os.sep) and full_path != abs_output_dir:
            print(f"Warning: Skipping file path attempting to write outside output directory: '{relative_file_path}' resolved to '{full_path}' (outside '{abs_output_dir}')", file=sys.stderr)
            continue

        file_dir = os.path.dirname(full_path)
        if file_dir and file_dir != abs_output_dir and not os.path.exists(file_dir):
            try:
                os.makedirs(file_dir)
                print(f"Created subdirectory: {file_dir}")
            except OSError as e:
                 print(f"Error creating subdirectory {file_dir} for {full_path}: {e}", file=sys.stderr)
                 continue

        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Wrote file: {full_path}")
            files_written += 1
        except Exception as e:
            print(f"Error writing file {full_path}: {e}", file=sys.stderr)

    print(f"--- Finished Storing Files ({files_written} written) ---")

# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Generate Robot Framework tests using a three-agent AI approach: Analysis, Generation, and Validation.")
    parser.add_argument("app_path", help="Path to the web application directory.")
    parser.add_argument("-c", "--context", help="Optional text context/instructions to provide to all AI agents.", default=None)
    parser.add_argument("-o", "--output", help="Output directory for generated tests.", default="robot_tests")
    parser.add_argument("--clear-output", action="store_true", help="Clear the output directory before writing new files.")
    parser.add_argument("--api-key", help="Gemini API Key (overrides environment variable).", default=None)
    parser.add_argument("--skip-validation", action="store_true", help="Skip the validation agent step.")
    parser.add_argument("--save-intermediate", action="store_true", help="Save intermediate files and plans for debugging.")

    args = parser.parse_args()

    # --- Get API Key ---
    api_key = args.api_key or os.getenv("GEMINI_API_KEY")
    # Fallback to hardcoded key if provided
    if not api_key:
         api_key="AIzaSyBTqClUsEwZpWskfPUAgVw1g8FvvnwvBxs" # Replace with your actual key if needed for testing

    if not api_key:
        print("Error: Gemini API Key not provided via argument (--api-key) or environment variable (GEMINI_API_KEY).", file=sys.stderr)
        sys.exit(1)

    # --- Validate Input Path ---
    if not os.path.isdir(args.app_path):
        print(f"Error: Path '{args.app_path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    # === Agent 1: Analysis ===
    print(f"\n=== Running Agent 1: Analysis ===")
    print(f"Traversing directory: {args.app_path}")
    # Update ignore patterns to include the specific output directory being used
    current_ignore_patterns = IGNORE_PATTERNS + [os.path.basename(args.output)]
    directory_structure = traverse_directory(args.app_path, current_ignore_patterns)

    if not directory_structure:
        print("Agent 1 Error: No files found to analyze after applying ignore patterns. Exiting.", file=sys.stderr)
        sys.exit(1)

    print("Preparing analysis prompt for Agent 1...")
    analysis_prompt = prepare_analysis_prompt(directory_structure, args.context)

    print("Interacting with Agent 1 (Analysis)...")
    analysis_response_text = interact_with_gemini(analysis_prompt, api_key, agent_name="Agent 1 (Analysis)")

    if analysis_response_text is None:
        print("Agent 1 Error: Failed to get response from AI. Exiting.", file=sys.stderr)
        sys.exit(1)

    analysis_plan = parse_analysis_response(analysis_response_text)

    if analysis_plan is None:
        print("Agent 1 Error: Failed to parse the analysis plan from AI response. Exiting.", file=sys.stderr)
        sys.exit(1)

    # Save intermediate plan if requested
    if args.save_intermediate:
        try:
            os.makedirs(args.output, exist_ok=True)
            plan_file_path = os.path.join(args.output, "intermediate_plan.json")
            with open(plan_file_path, 'w') as f:
                json.dump(analysis_plan, f, indent=2)
            print(f"Saved intermediate analysis plan to: {plan_file_path}")
        except Exception as e:
            print(f"Warning: Could not save intermediate plan: {e}")

    # === Agent 2: Generation ===
    print(f"\n=== Running Agent 2: Generation ===")
    print("Preparing generation prompt for Agent 2...")
    generation_prompt = prepare_generation_prompt(analysis_plan, args.context)

    print("Interacting with Agent 2 (Generation)...")
    generation_response_text = interact_with_gemini(generation_prompt, api_key, agent_name="Agent 2 (Generation)")

    if generation_response_text is None:
        print("Agent 2 Error: Failed to get response from AI. Exiting.", file=sys.stderr)
        sys.exit(1)

    print("Parsing generation response from Agent 2...")
    generated_files = parse_generation_response(generation_response_text)

    if not generated_files:
        print("Agent 2 Error: AI did not return any files to store based on the plan. Exiting.", file=sys.stderr)
        sys.exit(1)
    
    # Save intermediate files if requested
    if args.save_intermediate:
        intermediate_dir = os.path.join(args.output, "intermediate_generation")
        try:
            if os.path.exists(intermediate_dir):
                shutil.rmtree(intermediate_dir)
            os.makedirs(intermediate_dir, exist_ok=True)
            for rel_path, content in generated_files.items():
                file_path = os.path.join(intermediate_dir, rel_path)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            print(f"Saved intermediate generated files to: {intermediate_dir}")
        except Exception as e:
            print(f"Warning: Could not save intermediate files: {e}")

    # === Agent 3: Validation ===
    final_files = generated_files.copy()  # Default to generated files if no validation step

    if not args.skip_validation:
        print(f"\n=== Running Agent 3: Validation ===")
        print("Preparing validation prompt for Agent 3...")
        validation_prompt = prepare_validation_prompt(analysis_plan, generated_files, args.context)

        # --- Save validation prompt for debugging ---

        prompt_file_path = os.path.join('./', "validation_prompt.txt")
        os.makedirs(os.path.dirname(prompt_file_path), exist_ok=True) # Ensure output dir exists
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            f.write(validation_prompt)
        print(f"Saved validation prompt to: {prompt_file_path}")
           
        # --- End save validation prompt ---

        print("Interacting with Agent 3 (Validation)...")
        validation_response_text = interact_with_gemini(validation_prompt, api_key, agent_name="Agent 3 (Validation)")

        if validation_response_text is None:
            print("Agent 3 Warning: Failed to get response from validation agent. Proceeding with unvalidated files.", file=sys.stderr)
        else:
            print("Parsing validation response from Agent 3...")
            validation_report, validated_files = parse_validation_response(validation_response_text)
            
            # Save validation report if intermediate saving is enabled
            if args.save_intermediate and validation_report:
                try:
                    validation_report_path = os.path.join(args.output, "validation_report.json")
                    with open(validation_report_path, 'w') as f:
                        json.dump(validation_report, f, indent=2)
                    print(f"Saved validation report to: {validation_report_path}")
                except Exception as e:
                    print(f"Warning: Could not save validation report: {e}")
            
            # Log validation findings
            if validation_report:
                issues_found = validation_report.get('issues_found', False)
                issues = validation_report.get('issues', [])
                
                if issues_found:
                    print(f"Validation found {len(issues)} issues:")
                    for i, issue in enumerate(issues, 1):
                        print(f"  {i}. [{issue.get('file', 'Unknown')}] {issue.get('issue_type', 'Unknown issue')}: {issue.get('description', 'No description')}")
                    
                    # Update files with validated versions
                    if validated_files:
                        print(f"Applying fixes to {len(validated_files)} files...")
                        final_files.update(validated_files)
                    else:
                        print("Warning: Issues were found but no fixed files were provided.")
                else:
                    print("Validation complete: No issues found in generated code.")
            else:
                print("Warning: Could not parse validation report, proceeding with unvalidated files.")

    # === Store Files ===
    print(f"\n=== Storing Final Files ===")
    store_test_files(final_files, args.output, args.clear_output)

    print("\nTest generation process complete.")

if __name__ == "__main__":
    main()

    