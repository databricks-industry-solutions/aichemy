import os
import requests
import json
import streamlit as st
from databricks.sdk import WorkspaceClient
import base64


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
        raise Exception(
            f"Request failed with status {response.status_code}, {response.text}"
        )
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
    Parse function calls and thinking messages from text content.
    
    Expected format:
    <function_calls>
        <invoke name="function_name">
            <parameter name="param1">value1</parameter>
            <parameter name="param2">value2</parameter>
        </invoke>
    </function_calls>
    <thinking>
    Thinking message here
    </thinking>
    
    Returns:
        list: List of dicts with 'function_name', 'parameters', and 'thinking' keys
    """
    import re
    
    tool_calls = []
    
    # Find all function_calls blocks
    function_calls_pattern = r'<function_calls>\s*(.*?)\s*</function_calls>'
    function_calls_blocks = re.findall(function_calls_pattern, text_content, re.DOTALL)
    
    # Find all thinking blocks
    thinking_pattern = r'<thinking>\s*(.*?)\s*</thinking>'
    thinking_blocks = re.findall(thinking_pattern, text_content, re.DOTALL)
    
    # Parse each function_calls block
    for block in function_calls_blocks:
        # Find invoke tags
        invoke_pattern = r'<invoke name="([^"]+)">\s*(.*?)\s*</invoke>'
        invokes = re.findall(invoke_pattern, block, re.DOTALL)
        
        for function_name, params_block in invokes:
            # Parse parameters
            param_pattern = r'<parameter name="([^"]+)">([^<]*)</parameter>'
            params = re.findall(param_pattern, params_block)
            
            parameters = {param_name: param_value.strip() for param_name, param_value in params}
            
            tool_calls.append({
                'function_name': function_name,
                'parameters': parameters,
                'thinking': None  # Will be filled later
            })
    
    # Associate thinking blocks with tool calls (assume sequential order)
    for i, thinking in enumerate(thinking_blocks):
        if i < len(tool_calls):
            tool_calls[i]['thinking'] = thinking.strip()
    
    return tool_calls


def strip_tool_call_tags(text_content):
    """
    Strip <function_calls> and <thinking> tags and their contents from text.
    
    Args:
        text_content: Text containing function_calls and thinking tags
    
    Returns:
        str: Cleaned text with tags removed
    """
    import re
    
    # Remove function_calls blocks
    text_content = re.sub(r'<function_calls>\s*.*?\s*</function_calls>', '', text_content, flags=re.DOTALL)
    
    # Remove thinking blocks
    text_content = re.sub(r'<thinking>\s*.*?\s*</thinking>', '', text_content, flags=re.DOTALL)
    
    # Clean up extra whitespace and newlines
    text_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', text_content)
    text_content = text_content.strip()
    
    return text_content


def extract_tokens_from_spans(response_json: dict):
    """Recursively extract tokens from spans and stream to file"""
    spans = response_json.get('databricks_output', {}).get('trace', {}).get('data', {}).get('spans', [])

    global token_count
    for span in spans:
        if 'events' in span and span['events']:
            for event in span['events']:
                if 'attributes' in event and 'token' in event['attributes']:
                    token = event['attributes']['token']
                    tokens.append(token)
                    token_count += 1
                    
                    # Write token immediately to file
                    output_file.write(f"{token_count}. {token}\n")
                    output_file.flush()
                    
                    # Print to console
                    print(f"{token_count}. {repr(token)}")

