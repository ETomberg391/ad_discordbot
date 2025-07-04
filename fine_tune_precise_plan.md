# Final Definitive Plan v4: Two-Pass Architecture with Few-Shot Prompting

## 1. The Core Insight

The user correctly identified that the two-pass architecture is fundamentally sound, but the Refiner pass is inconsistent. The solution is not to abandon the architecture, but to improve the instructions given to the Refiner.

## 2. The Final Architecture: Two-Pass with a Better Prompt

The system will use the two-pass architecture. The key change is the implementation of a "few-shot" prompt for the second pass, which gives the AI a direct command and a clear example to follow, making its output far more reliable.

### Pass 1: Creative Pass
*   **Function:** `custom_chatbot_wrapper`
*   **Goal:** Generate a rich, in-character response. This is working correctly.

### Pass 2: Refiner Pass
*   **Function:** `generate_reply`
*   **Goal:** Clean and format the output from Pass 1.
*   **The Fix:** Use a new, non-conversational "few-shot" prompt that provides a clear example of the required transformation.

## 3. The New "Few-Shot" Refiner Prompt

```python
refiner_prompt_template = """Transform the following text into a clean response. Remove all third-person descriptions and meta-commentary. Enclose the final, pure first-person response in <chatting> tags.

--- EXAMPLE ---
TEXT TO REFINE:
*He tilts his head.* I am well, thank you. How are you?

REFINED OUTPUT:
<chatting>I am well, thank you. How are you?</chatting>
--- END EXAMPLE ---

--- TASK ---
TEXT TO REFINE:
{pass1_raw_output}

REFINED OUTPUT:
"""
```

## 4. Implementation Steps

1.  **User Approval:** Confirm this final plan, centered on the new refiner prompt, is correct.
2.  **Switch to Code Mode:** Transition to implement the code changes.
3.  **Modify `modules/precise_chat_module.py`:**
    *   Replace the old `refiner_prompt` string with the new `refiner_prompt_template`.
    *   Update the call to `generate_reply` to correctly format the prompt with the output from Pass 1.