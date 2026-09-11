from __future__ import annotations


def init_pipe(pipe, kwargs, profile):
    """
    Standalone MMGP profile initialization for ComfyMax FlashVSR.

    Based on the WanGP init_pipe logic, stripped of WanGP-specific
    command-line arguments, server config, MPS handling and secondary
    model logic that FlashVSR Tiny does not use.
    """

    preload = 0

    kwargs["extraModelsToQuantize"] = None

    source_budgets = kwargs.get("budgets")
    if source_budgets is None:
        source_budgets = {}
        kwargs["budgets"] = source_budgets

    mmgp_profile = int(profile)

    if mmgp_profile in (2, 4, 5):
        existing_budget = kwargs.get("budgets", 100)

        if isinstance(existing_budget, dict):
            default_transformer_budget = existing_budget.get("transformer", 100)
        else:
            default_transformer_budget = existing_budget

        budgets = {
            "transformer": default_transformer_budget if preload == 0 else preload,
            "text_encoder": 100 if preload == 0 else preload,
            "*": max(1000 if mmgp_profile == 5 else 3000, preload),
        }

        source_budgets.update(budgets)

    elif mmgp_profile == 3:
        source_budgets.update({
            "*": "70%"
        })

    return mmgp_profile