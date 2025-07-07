import re
import asyncio
from functools import partial
import copy
from modules.utils_tgwui import custom_chatbot_wrapper
from modules.text_generation import generate_reply
from modules.utils_asyncio import generate_in_executor
import os
from datetime import datetime

LOG_DIR = 'modules/precise_logs'
SESSION_LOG_FILE = None

def _initialize_session_log():
    """(Internal) Creates a single log file for the bot's entire session."""
    global SESSION_LOG_FILE
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    SESSION_LOG_FILE = os.path.join(LOG_DIR, f"session_{timestamp}.log")

def log_precise_entry(input_text, attempts_list, final_answer, source):
    """Logs a complete interaction entry to the session log file, supporting two-pass architecture."""
    if not SESSION_LOG_FILE:
        return

    log_content = (
        f"--- ENTRY @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')} ---\n"
        f"--- INPUT ---\n{input_text}\n\n"
    )

    for i, attempt_data in enumerate(attempts_list):
        pass1_out = attempt_data.get("pass1_creative_output", "N/A")
        pass2_out = attempt_data.get("pass2_refined_output", "N/A")
        log_content += (
            f"--- ATTEMPT {i + 1} ---\n"
            f"--- PASS 1 (Creative) RAW OUTPUT ---\n{pass1_out}\n\n"
            f"--- PASS 2 (Refiner) RAW OUTPUT ---\n{pass2_out}\n\n"
        )

    log_content += (
        f"--- FINAL ANSWER ({source}) ---\n{final_answer}\n"
        f"--------------------------------------------------\n\n"
    )

    with open(SESSION_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_content)

# Initialize the log file once, when this module is first imported.
_initialize_session_log()


async def get_precise_answer(text, state, **kwargs):
    """
    Generates a precise answer using a two-pass refinement architecture.
    1. Creative Pass: Generates a rich, in-character response.
    2. Refiner Pass: Cleans and formats the response from Pass 1.
    """
    state['skip_html_escape'] = True

    # This prompt is designed to minimize conversational filler from the refiner model.
    refiner_prompt_template = "Your task is to enclose the provided text in <chatting> tags. Output only the tagged text, with no additional commentary.\n\nInput:\n{creative_output}\n\nOutput:\n"

    max_retries = 4
    attempts_list = []

    for attempt in range(max_retries):
        # --- PASS 1: CREATIVE ---
        # Use a deepcopy of the state to avoid polluting the main history.
        creative_state = copy.deepcopy(state)

        creative_func = partial(custom_chatbot_wrapper, text=text, state=creative_state, **kwargs)
        creative_generator = generate_in_executor(creative_func)
        pass1_raw_output = ""
        async for response_chunk in creative_generator:
            if response_chunk.get('internal') and isinstance(response_chunk['internal'], list) and len(response_chunk['internal']) > 0:
                pass1_raw_output = response_chunk['internal'][-1][1]

        # --- PASS 2: REFINER ---
        # Start with a copy of the original state to ensure all necessary keys are present.
        refiner_state = copy.deepcopy(state)

        # Override with settings specific to the refiner pass.
        refiner_state.update({
            'max_new_tokens': len(pass1_raw_output) + 50,  # Allow enough tokens for tags and minor variance
            'temperature': 0.7,
            'top_p': 0.8,
            'top_k': 20,
            'repetition_penalty': 1.0,
            'stopping_strings': ['</chatting>'],
            'custom_stopping_strings': [],
            'stream': False,
            'seed': -1,
        })

        # The refiner pass is not a chat and uses a self-contained prompt, so clear history.
        refiner_state['history'] = {'internal': [], 'visible': []}
        
        refiner_prompt_text = refiner_prompt_template.format(creative_output=pass1_raw_output)
        
        # Use the low-level generate_reply for raw text completion
        pass2_refined_output = ""
        reply_generator = generate_reply(refiner_prompt_text, refiner_state, is_chat=False)
        for reply in reply_generator:
            pass2_refined_output = reply
        
        # Add the closing tag back if it was used as a stop string
        if not pass2_refined_output.endswith('</chatting>'):
            pass2_refined_output += '</chatting>'

        attempts_list.append({
            "pass1_creative_output": pass1_raw_output,
            "pass2_refined_output": pass2_refined_output
        })

        # --- FINAL EXTRACTION ---
        # The model may include internal thoughts or conversational text. We must strip all of that out
        # and extract only the content from the final <chatting> block.

        # 1. Remove any <think>...</think> blocks first.
        cleaned_output = re.sub(r'<think>.*?</think>', '', pass2_refined_output, flags=re.DOTALL).strip()

        # 2. Find the last <chatting> block and extract its content.
        if '<chatting>' in cleaned_output:
            # Isolate the part after the last opening tag, discarding any text before it.
            content_after_last_open_tag = cleaned_output.rsplit('<chatting>', 1)[-1]
            # Isolate the part before the first closing tag that follows.
            final_answer = content_after_last_open_tag.split('</chatting>', 1)[0].strip()

            if final_answer:  # Ensure we extracted a non-empty answer.
                log_precise_entry(text, attempts_list, final_answer, f"from attempt {attempt + 1}")
                return final_answer

        if attempt < max_retries - 1:
            await asyncio.sleep(1)

    # Fallback if all retries fail
    final_fallback_response = "I am sorry, I am having trouble formulating a response."
    log_precise_entry(text, attempts_list, final_fallback_response, f"fallback after {max_retries} retries")
    return final_fallback_response
