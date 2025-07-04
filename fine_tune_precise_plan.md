# Final Definitive Plan v6: Consistent Default Settings

## 1. The Core Insight

The user has correctly identified that the refiner pass should use the application's default settings, not the character's settings. However, the default settings must be robust enough for the task. The solution is to improve the default settings to ensure model behavior is consistent between the creative and refiner passes.

## 2. The Final Architecture: Improved Default State

The system will use the two-pass architecture. The key is to modify `settings_templates/dict_base_settings.yaml` to provide a stable baseline.

### Pass 1: Creative Pass
*   **State:** Uses the character-specific settings (e.g., from `Ecne_Bot.yaml`), which override the defaults.

### Pass 2: Refiner Pass
*   **State:** Uses the improved default settings from `dict_base_settings.yaml`.
*   **Benefit:** This ensures critical parameters like `stopping_strings` are present, preventing the refiner from "thinking out loud," while maintaining a clean separation from the character's specific context.

## 3. The "Few-Shot" Refiner Prompt
The refiner will continue to use the superior "few-shot" prompt we previously designed.

## 4. Implementation Steps

1.  **User Approval:** Confirm this final plan, centered on improving the default settings, is correct.
2.  **Switch to Code Mode:** Transition to implement the code changes.
3.  **Modify `settings_templates/dict_base_settings.yaml`:**
    *   Copy the values for `max_new_tokens`, `repetition_penalty_range`, `add_bos_token`, `custom_stopping_strings`, and `stopping_strings` from `Ecne_Bot.yaml` into the `llmstate.state` section of `dict_base_settings.yaml`.