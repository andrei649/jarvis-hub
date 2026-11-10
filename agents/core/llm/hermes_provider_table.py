"""The reviewed table of model providers Nerva runs from Hermes's profiles (Adopt lane, slice 2).

Pure data, no imports: the settings select, the managed-key list and the bridge
(``hermes_profiles``) all read it without loading vendored code. One row per provider id:
the vendored module that registers it (``agents/vendor/hermes/plugins/model-providers/<dir>``),
the key names it may read (the profile's ``env_vars`` without its ``*_BASE_URL`` overrides,
in the profile's order), and a display name for profiles that declare none.
``tests/test_hermes_model_providers.py`` pins each row against the vendored profile.

Guide: ``docs/hermes/ADOPT_LANE.md`` ("Model providers").
"""

#: (provider id, vendored directory, key names, display name when the profile has none)
ADOPTED_MODEL_PROVIDERS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("ai-gateway", "ai-gateway", ("AI_GATEWAY_API_KEY",), "Vercel AI Gateway"),
    ("alibaba", "alibaba", ("DASHSCOPE_API_KEY",), "Alibaba Cloud DashScope"),
    ("alibaba-cn", "alibaba", ("DASHSCOPE_API_KEY",), ""),
    ("alibaba-token-plan", "alibaba", ("ALIBABA_TOKEN_PLAN_API_KEY",), ""),
    ("alibaba-token-plan-cn", "alibaba", ("ALIBABA_TOKEN_PLAN_CN_API_KEY", "ALIBABA_TOKEN_PLAN_API_KEY"), ""),
    ("alibaba-coding-plan", "alibaba-coding-plan", ("ALIBABA_CODING_PLAN_API_KEY", "DASHSCOPE_API_KEY"), ""),
    ("alibaba-coding-plan-cn", "alibaba-coding-plan",
     ("ALIBABA_CODING_PLAN_CN_API_KEY", "ALIBABA_CODING_PLAN_API_KEY", "DASHSCOPE_API_KEY"), ""),
    ("arcee", "arcee", ("ARCEEAI_API_KEY",), "Arcee AI"),
    # ``deepseek`` loads before ``commandcode``: CommandCode's DeepSeek ids reuse the
    # DeepSeek profile's request controls through the registry.
    ("deepseek", "deepseek", ("DEEPSEEK_API_KEY",), ""),
    ("commandcode", "commandcode", ("COMMANDCODE_API_KEY",), ""),
    ("fireworks", "fireworks", ("FIREWORKS_API_KEY",), ""),
    ("gmi", "gmi", ("GMI_API_KEY",), ""),
    ("huggingface", "huggingface", ("HF_TOKEN",), ""),
    ("kilocode", "kilocode", ("KILOCODE_API_KEY",), "Kilo Code"),
    ("kimi-coding", "kimi-coding", ("KIMI_API_KEY", "KIMI_CODING_API_KEY"), "Kimi (Moonshot)"),
    ("kimi-coding-cn", "kimi-coding", ("KIMI_CN_API_KEY",), "Kimi (Moonshot, China)"),
    ("nebius-token-factory", "nebius-token-factory", ("NEBIUS_API_KEY", "NEBIUS_TOKEN_FACTORY_API_KEY"), ""),
    ("novita", "novita", ("NOVITA_API_KEY",), ""),
    ("nvidia", "nvidia", ("NVIDIA_API_KEY",), ""),
    ("ollama-cloud", "ollama-cloud", ("OLLAMA_API_KEY",), "Ollama Cloud"),
    ("stepfun", "stepfun", ("STEPFUN_API_KEY",), "StepFun"),
    ("upstage", "upstage", ("UPSTAGE_API_KEY",), ""),
    ("xiaomi", "xiaomi", ("XIAOMI_API_KEY",), "Xiaomi MiMo"),
    ("zai", "zai", ("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"), ""),
)

ADOPTED_MODEL_PROVIDER_IDS: tuple[str, ...] = tuple(row[0] for row in ADOPTED_MODEL_PROVIDERS)
ADOPTED_MODEL_PROVIDER_KEYS: frozenset[str] = frozenset(
    name for row in ADOPTED_MODEL_PROVIDERS for name in row[2])
