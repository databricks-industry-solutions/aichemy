import os
import requests
import json
import streamlit as st
from databricks.sdk import WorkspaceClient
import base64
from pathlib import Path
from typing import Optional, Union, List
import yaml
import re


def get_user_info():
    headers = st.context.headers
    return dict(
        user_name=headers.get("X-Forwarded-Preferred-Username"),
        user_email=headers.get("X-Forwarded-Email"),
        user_id=headers.get("X-Forwarded-User"),
    )


def ask_agent(input_dict: dict, w: WorkspaceClient = None) -> requests.models.Response:
    # Example input_dict:
    # input_dict = {
    #     "input": [
    #         {"role": "user", "content": "What is the latest customer service request?"}
    #     ],
    #     "custom_inputs": {"thread_id": "1001"},
    # }
    url = f'https://e2-demo-field-eng.cloud.databricks.com/serving-endpoints/{os.getenv("SERVING_ENDPOINT")}/invocations'
    if w is None:
        w = WorkspaceClient()
    headers = w.config.authenticate()
    response = requests.post(
        headers=headers,
        url=url,
        json=input_dict,
    )
    if response.status_code != 200:
        raise Exception(f"Request failed with status {response.status_code}, {response.text}")
    return response


def ask_agent_mlflowclient(input_dict: dict, client) -> dict:
    # returns response.json()
    return client.predict(endpoint=os.getenv("SERVING_ENDPOINT"), inputs=input_dict)


def extract_text_content(response_json):
    # Extract text content from the response (equivalent to jq extraction)
    # jq -r '.output[] | select(.type == "message") | .content[] | .text'
    text_contents = []
    for output_item in response_json.get("output", []):
        if output_item.get("type") == "message":
            new_text = output_item.get("content")[0].get("text")
            if new_text not in text_contents:
                text_contents.append(new_text)
    return text_contents


def parse_tool_calls(text_content):
    """
    Parse function calls and MCP calls from text content.
    Processes tags in order: thinking/mcp_result follow their respective tool calls.

    Expected formats:
    
    Format 1 - function_calls followed by thinking:
    <function_calls>
        <invoke name="function_name">
            <parameter name="param1">value1</parameter>
        </invoke>
    </function_calls>
    <thinking>Thinking message here</thinking>
    
    Format 2a - mcp_call with nested tags:
    <mcp_call>
        <server_name>opentargets</server_name>
        <tool_name>get_target_interactions</tool_name>
        <arguments>{"target_id": "ENSG00000091831"}</arguments>
    </mcp_call>
    <mcp_result>Result content here</mcp_result>
    
    Format 2b - mcp_call with attributes:
    <mcp_call tool_name="search_compounds" server_name="pubchem-mcp-server">
    {"query": "aspirin", "max_results": 1}
    </mcp_call>
    
    Format 3 - JSON tool call:
    {"tool_name": "search_pubmed", "arguments": {"query": "aspirin", "max_results": 10}}

    Returns:
        list: List of dicts with 'function_name', 'parameters', and 'thinking' keys
    """
    import re

    tool_calls = []

    # Combined pattern to find all tag types in order of appearance
    # Groups: 1-2=function_calls, 3-4-5=mcp_call, 6-7-8=json_tool_call(arguments),
    #         9-10-11=json_tool_call(parameters), 12-13=thinking, 14-15=mcp_result
    combined_pattern = (
        r"(<function_calls>\s*(.*?)\s*</function_calls>)|"
        r"(<mcp_call([^>]*)>\s*(.*?)\s*</mcp_call>)|"
        r'(\n{"tool_name":\s*"([^"]+)",\s*"arguments":\s*(\{[^}]*\})\})|'
        r'(\n{"tool_name":\s*"([^"]+)",\s*"parameters":\s*(\{[^}]*\})\})|'
        r"(<thinking>\s*(.*?)\s*</thinking>)|"
        r"(<mcp_result>\s*(.*?)\s*</mcp_result>)"
    )

    for match in re.finditer(combined_pattern, text_content, re.DOTALL):
        if match.group(1):  # function_calls block
            block = match.group(2)

            # Find invoke tags within this block
            invoke_pattern = r'<invoke name="([^"]+)">\s*(.*?)\s*</invoke>'
            invokes = re.findall(invoke_pattern, block, re.DOTALL)

            for function_name, params_block in invokes:
                # Parse parameters
                param_pattern = r'<parameter name="([^"]+)">([^<]*)</parameter>'
                params = re.findall(param_pattern, params_block)
                parameters = {param_name: param_value.strip() for param_name, param_value in params}

                tool_calls.append(
                    {"function_name": function_name, "parameters": parameters, "thinking": None}
                )

        elif match.group(3):  # mcp_call block
            attrs = match.group(4)  # Attributes in opening tag (may be empty)
            body = match.group(5)   # Body content

            # Try to extract from attributes first (Format 2b)
            tool_attr = re.search(r'tool_name="([^"]+)"', attrs)
            server_attr = re.search(r'server_name="([^"]+)"', attrs)

            if tool_attr:
                # Format 2b: attributes in opening tag, JSON body
                tool_name = tool_attr.group(1).strip()
                server_name = server_attr.group(1).strip() if server_attr else ""
                args_str = body.strip()
            else:
                # Format 2a: nested tags
                server_match = re.search(r"<server_name>\s*(.*?)\s*</server_name>", body, re.DOTALL)
                server_name = server_match.group(1).strip() if server_match else ""

                tool_match = re.search(r"<tool_name>\s*(.*?)\s*</tool_name>", body, re.DOTALL)
                tool_name = tool_match.group(1).strip() if tool_match else "unknown"

                args_match = re.search(r"<arguments>\s*(.*?)\s*</arguments>", body, re.DOTALL)
                args_str = args_match.group(1).strip() if args_match else ""

            # Parse arguments JSON
            parameters = {}
            if args_str:
                # Clean up malformed JSON
                args_str = re.sub(r"^['\"]?\{?", "{", args_str)
                args_str = re.sub(r"\}?['\"]?$", "}", args_str)
                try:
                    parameters = json.loads(args_str)
                except json.JSONDecodeError:
                    # Fallback: parse key-value pairs
                    param_pairs = re.findall(r'"([^"]+)":\s*("[^"]*"|\d+|true|false|null)', args_str)
                    for key, value in param_pairs:
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        parameters[key] = value

            function_name = f"{server_name}:{tool_name}" if server_name else tool_name

            tool_calls.append(
                {"function_name": function_name, "parameters": parameters, "thinking": None}
            )

        elif match.group(6):  # JSON tool call with "arguments": {"tool_name": "...", "arguments": {...}}
            tool_name = match.group(7)
            args_str = match.group(8)

            parameters = {}
            if args_str:
                try:
                    parameters = json.loads(args_str)
                except json.JSONDecodeError:
                    # Fallback: parse key-value pairs
                    param_pairs = re.findall(r'"([^"]+)":\s*("[^"]*"|\d+|true|false|null)', args_str)
                    for key, value in param_pairs:
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        parameters[key] = value

            tool_calls.append(
                {"function_name": tool_name, "parameters": parameters, "thinking": None}
            )

        elif match.group(9):  # JSON tool call with "parameters": {"tool_name": "...", "parameters": {...}}
            tool_name = match.group(10)
            args_str = match.group(11)

            parameters = {}
            if args_str:
                try:
                    parameters = json.loads(args_str)
                except json.JSONDecodeError:
                    # Fallback: parse key-value pairs
                    param_pairs = re.findall(r'"([^"]+)":\s*("[^"]*"|\d+|true|false|null)', args_str)
                    for key, value in param_pairs:
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        parameters[key] = value

            tool_calls.append(
                {"function_name": tool_name, "parameters": parameters, "thinking": None}
            )

        elif match.group(12):  # thinking block - associate with last tool call
            thinking = match.group(13).strip()
            if tool_calls and tool_calls[-1]["thinking"] is None:
                tool_calls[-1]["thinking"] = thinking

        elif match.group(14):  # mcp_result block - associate with last tool call
            result = match.group(15).strip()
            if tool_calls and tool_calls[-1]["thinking"] is None:
                tool_calls[-1]["thinking"] = result

    return tool_calls


def _remove_balanced_structures(text):
    """Remove balanced [] and {} structures that look like data output."""
    result = []
    i = 0
    while i < len(text):
        # Check for start of list or dict
        if text[i] in '[{':
            # Look back to see if this is at start of line or after whitespace/newline
            prev_is_boundary = (i == 0 or text[i-1] in '\n\r \t')
            
            if prev_is_boundary:
                # Check if it looks like a data structure (has quotes after opening)
                lookahead = text[i:i+10]
                if (text[i] == '[' and "'" in lookahead[:5]) or \
                   (text[i] == '[' and '"' in lookahead[:5]) or \
                   (text[i] == '{' and "'" in lookahead[:5]) or \
                   (text[i] == '{' and '"' in lookahead[:5]):
                    # Find matching closing bracket
                    open_char = text[i]
                    close_char = ']' if open_char == '[' else '}'
                    depth = 1
                    j = i + 1
                    in_string = False
                    string_char = None
                    
                    while j < len(text) and depth > 0:
                        c = text[j]
                        if in_string:
                            if c == string_char and text[j-1] != '\\':
                                in_string = False
                        else:
                            if c in '"\'':
                                in_string = True
                                string_char = c
                            elif c == open_char:
                                depth += 1
                            elif c == close_char:
                                depth -= 1
                            elif c == '{':
                                depth += 1
                            elif c == '}' and open_char == '[':
                                pass  # Don't count } when looking for ]
                            elif c == '}':
                                depth -= 1
                        j += 1
                    
                    if depth == 0:
                        # Skip this structure, consume trailing whitespace
                        while j < len(text) and text[j] in ' \t\n\r':
                            j += 1
                        i = j
                        continue
        
        result.append(text[i])
        i += 1
    
    return ''.join(result)


def strip_tool_call_tags(text_content):
    """
    Strip <function_calls>, <mcp_call>, <mcp_result>, <thinking> tags, and JSON-like output from text.

    Args:
        text_content: Text containing function_calls, mcp_call, mcp_result, thinking tags, or JSON/dict output

    Returns:
        str: Cleaned text with tags and JSON output removed
    """
    import re

    # Remove function_calls blocks - closing tag may vary (</function_calls>, </invoke>, etc.)
    # The final closing tag is distinguished by NOT having another < within 5 chars after it
    # Inner tags like </parameter> are immediately followed by more XML content
    text_content = re.sub(r"<function_calls>.*?</\w+>(?!.{0,5}<)\s*", "", text_content, flags=re.DOTALL)

    # Remove mcp_call blocks (both formats)
    text_content = re.sub(r"<mcp_call[^>]*>.*?</mcp_call>\s*", "", text_content, flags=re.DOTALL)

    # Remove mcp_result blocks
    text_content = re.sub(r"<mcp_result>.*?</mcp_result>\s*", "", text_content, flags=re.DOTALL)

    # Remove thinking blocks
    text_content = re.sub(r"<thinking>\s*.*?\s*</thinking>", "", text_content, flags=re.DOTALL)

    # Remove JSON tool calls: {"tool_name": "...", "arguments": {...}}
    text_content = re.sub(r'\{"tool_name":\s*"[^"]+",\s*"arguments":\s*\{.*?\}\}\s*', "", text_content, flags=re.DOTALL)

    # Remove list of dicts: [{'key': ...}] or [{"key": ...}] - matches from [{ to final }]
    text_content = re.sub(r'\[\s*\{[\'"][\s\S]*?\}\s*\]', "", text_content)

    # Remove standalone dicts at start of line: {'key': ...} or {"key": ...}
    text_content = re.sub(r'(?:^|\n)\s*\{[\'"][^}]*(?:\{[^}]*\}[^}]*)?\}\s*(?=\n|$)', "\n", text_content, flags=re.MULTILINE)

    # Clean up extra whitespace and newlines
    text_content = re.sub(r"\n\s*\n\s*\n+", "\n\n", text_content)
    text_content = text_content.strip()

    return text_content


def parse_genie_results(response_json):
    """
    Parse response JSON for poll_query_results spans and extract result and query from spanOutputs.

    Args:
        response_json: Dictionary or JSON string containing the response data

    Returns:
        list: List of dictionaries containing extracted poll_query_results data.
              Each dict has: 'result', 'query', 'description', 'conversation_id'
              Returns empty list if no poll_query_results spans found.
    """
    # Convert string to dict if needed
    if isinstance(response_json, str):
        response_json = json.loads(response_json)

    results = []

    # Navigate to spans
    try:
        spans = response_json.get("databricks_output", {}).get("trace", {}).get("data", {}).get("spans", [])
    except (AttributeError, KeyError):
        return results

    # Find all poll_query_results spans
    for span in spans:
        span_name = span.get("name", "")
        if span_name == "poll_query_results":
            attributes = span.get("attributes", {})
            span_outputs = attributes.get("mlflow.spanOutputs", "{}")

            # Parse the spanOutputs JSON string
            try:
                outputs = json.loads(span_outputs)
                result_data = {
                    "result": outputs.get("result", ""),
                    "query": outputs.get("query", ""),
                    "description": outputs.get("description", ""),
                }
                results.append(result_data)
            except json.JSONDecodeError:
                continue
    return results


# ============================================================================
# Skill Loading Utilities
# ============================================================================


def get_skills_directory() -> Path:
    """
    Get the path to the skills directory.

    Returns:
        Path: Path to the skills directory
    """
    # Navigate from app folder to project root, then to skills
    app_root = Path(__file__).resolve().parent
    project_root = app_root.parent.parent
    return project_root / "skills"


def parse_skill_frontmatter(content: str) -> dict:
    """
    Parse YAML frontmatter from a SKILL.md file.

    Expected format:
    ---
    name: skill-name
    description: Skill description text
    ---

    Args:
        content: The full content of the SKILL.md file

    Returns:
        dict: Parsed frontmatter with 'name' and 'description' keys
    """
    frontmatter = {}

    # Match YAML frontmatter between --- delimiters
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    match = re.match(frontmatter_pattern, content, re.DOTALL)

    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            pass

    return frontmatter or {}


def discover_skills(skills_dir: Optional[Union[str, Path]] = None) -> list[dict]:
    """
    Discover all available skills from the skills directory.

    Scans the skills directory for subdirectories containing SKILL.md files,
    parses their frontmatter, and returns a list of skill metadata.

    Returns:
        list: List of dicts with keys:
              - 'name': Display name from frontmatter
              - 'description': Description from frontmatter
              - 'path': Full path to the skill directory
              - 'label': Formatted display label with emoji for UI
              - 'caption': Truncated description for UI captions
    """
    if not skills_dir:
        skills_dir = get_skills_directory()
    skills = {}

    if not skills_dir.exists():
        return skills

    for skill_folder in skills_dir.iterdir():
        if skill_folder.is_dir():
            skill_file = skill_folder / "SKILL.md"
            if skill_file.exists():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    frontmatter = parse_skill_frontmatter(content)

                    name = frontmatter.get("name", skill_folder.name)
                    description = frontmatter.get("description", "")
                    
                    # Generate label with emoji based on skill type
                    if "target" in name.lower():
                        label = f"🎯 {smart_title(name.replace('-', ' '))}"
                        order = 0
                    elif "hit" in name.lower():
                        label = f"⌬ {smart_title(name.replace('-', ' '))}"
                        order = 1
                    elif "adme" in name.lower():
                        label = f"🧪 {smart_title(name.replace('-', ' '))}"
                        order = 2
                    elif "safety" in name.lower():
                        label = f"☠️ {smart_title(name.replace('-', ' '))}"
                        order = 3
                    else:
                        label = f"📋 {smart_title(name.replace('-', ' '))}"
                        order = 4
                    # Generate truncated caption
                    caption = description.split(". ")[0] if description else ""
                    if len(caption) > 70:
                        caption = caption[:67] + "..."

                    skill_info = {
                        "description": description,
                        "path": str(skill_folder),
                        "label": label,
                        "caption": caption,
                        "order": order,
                    }
                    skills[name] = skill_info
                except Exception:
                    # Skip skills that can't be parsed
                    continue

    return skills


def load_skill_content(skill_name: str, skills_dir: Optional[Union[str, Path]] = None) -> Optional[dict]:
    """
    Load the full content of a skill including the main SKILL.md and any reference files.

    Args:
        skill_name: The skill directory name (e.g., 'target-identification')

    Returns:
        dict: Dictionary containing:
              - 'frontmatter': Parsed YAML frontmatter
              - 'content': Full markdown content (without frontmatter)
              - 'references': Dict mapping reference filenames to their content
              - 'full_prompt': Combined prompt ready for injection
        None: If skill not found or cannot be loaded
    """
    if not skills_dir:
        skills_dir = get_skills_directory()
    skill_path = skills_dir / skill_name
    skill_file = skill_path / "SKILL.md"

    if not skill_file.exists():
        return None

    try:
        full_content = skill_file.read_text(encoding="utf-8")

        # Parse frontmatter
        frontmatter = parse_skill_frontmatter(full_content)

        # Extract content without frontmatter
        content_pattern = r"^---\s*\n.*?\n---\s*\n(.*)$"
        match = re.match(content_pattern, full_content, re.DOTALL)
        content = match.group(1).strip() if match else full_content

        # Load reference files
        references = {}
        references_dir = skill_path / "references"
        if references_dir.exists():
            for ref_file in references_dir.iterdir():
                if ref_file.is_file() and ref_file.suffix == ".md":
                    try:
                        references[ref_file.name] = ref_file.read_text(encoding="utf-8")
                    except Exception:
                        continue

        # Build full prompt with references appended
        full_prompt = f"# Skill: {frontmatter.get('name', skill_name)}\n\n"
        full_prompt += content

        if references:
            full_prompt += "\n\n---\n\n## Reference Materials\n\n"
            for ref_name, ref_content in references.items():
                full_prompt += f"### {ref_name}\n\n{ref_content}\n\n"

        return {"frontmatter": frontmatter, "content": content, "references": references, "full_prompt": full_prompt}

    except Exception:
        return None


def build_prompt_with_skill(user_query: str, skill_name: Optional[str] = None, skills_dir: Optional[Union[str, Path]] = None) -> str:
    """
    Build a prompt that includes skill instructions if a skill is selected.

    Args:
        user_query: The user's original query
        skill_name: Optional skill name to load and prepend

    Returns:
        str: The combined prompt with skill instructions (if applicable)
    """
    if not skill_name:
        return user_query

    skill_data = load_skill_content(skill_name, skills_dir)
    if not skill_data:
        return user_query

    # Build prompt with skill context
    prompt = f"""You have been given a specialized skill to help with this task. Follow the workflow instructions carefully.

<skill_instructions>
{skill_data['full_prompt']}
</skill_instructions>

<user_request>
{user_query}
</user_request>

Execute the skill workflow to address the user's request. Follow each step methodically and provide the expected output format."""

    return prompt


def extract_user_request(prompt: str) -> str:
    """
    Extract the user query from between <user_request> tags.

    If the prompt contains <user_request> tags, extracts and returns only the
    content between them. Otherwise, returns the original prompt unchanged.

    Args:
        prompt: The full prompt, potentially containing <user_request> tags

    Returns:
        str: The extracted user request, or the original prompt if no tags found
    """
    pattern = r"<user_request>\s*(.*?)\s*</user_request>"
    match = re.search(pattern, prompt, re.DOTALL)

    if match:
        return match.group(1).strip()

    return prompt


def smart_title(s):
    # Split the string into words based on whitespace
    words = s.split()
    processed_words = []
    for w in words:
        # Check if the word is entirely uppercase
        if w.isupper():
            processed_words.append(w) # Leave it unchanged
        else:
            processed_words.append(w.title()) # Apply title case
    # Rejoin the words with a single space
    return ' '.join(processed_words)