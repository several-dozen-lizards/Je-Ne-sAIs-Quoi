# Choose and connect a model

JNAIQ supports local Ollama, Anthropic's API, and OpenAI-compatible chat
endpoints. Provider presets fill in the connection details. Model availability
changes, so use **Load available models** for the connection's current catalog,
or copy an exact model ID from the provider. Suggested IDs and a saved key do
not establish permission, balance, regional availability, or model capabilities.

## The ordinary setup

1. Start JNAIQ. Open **Settings → API keys**, find your provider's slot, paste
   the key, and save. You can do this before registering any model. Keys remain
   in the local, gitignored `.env`; model files contain slot names only.
2. Open **Household → Install a model**. Choose the connection type, then the
   provider. For a preset already installed in the model dropdown, use that
   entry directly: it retains the model's declared wire settings.
3. Load the catalog or enter a model ID. Give it a short JNAIQ name and set its
   context window from the model card. Install registers a connection; it does
   not download a local model, start a server, or prove a cloud call works.
4. Choose it when creating a persona, or add it to an existing persona's roster
   and start the selected model. Identity and local history stay with the persona.

Generic new registrations start with conservative capabilities. A model card
and a successful text reply do not automatically validate images or tool use.

## Hosted provider presets

Use **Anthropic API** for Anthropic. For the remaining rows, choose
**OpenAI-compatible · hosted or local** and the named provider.

| Provider | Credential slot | Where to obtain access |
| --- | --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) |
| OpenAI | `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) |
| Google Gemini | `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |
| Amazon Bedrock | `AWS_BEARER_TOKEN_BEDROCK` | [Bedrock API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) |
| OpenRouter | `OPENROUTER_API_KEY` | [OpenRouter](https://openrouter.ai/settings/keys) |
| Together AI | `TOGETHER_API_KEY` | [Together](https://api.together.ai/) |
| Groq | `GROQ_API_KEY` | [Groq Console](https://console.groq.com/keys) |
| Mistral | `MISTRAL_API_KEY` | [Mistral Console](https://console.mistral.ai/) |
| DeepSeek | `DEEPSEEK_API_KEY` | [DeepSeek Platform](https://platform.deepseek.com/) |
| Meta Model API / Muse | `MODEL_API_KEY` | [Meta](https://developers.meta.com/ai/) |
| Kimi / Moonshot AI | `MOONSHOT_API_KEY` | [Moonshot Platform](https://platform.moonshot.ai/) |
| Z.AI / GLM | `ZAI_API_KEY` | [Z.AI](https://open.bigmodel.cn/) |
| xAI / Grok | `XAI_API_KEY` | [xAI Console](https://console.x.ai/) |
| Fireworks AI | `FIREWORKS_API_KEY` | [Fireworks](https://fireworks.ai/) |
| DeepInfra | `DEEPINFRA_API_KEY` | [DeepInfra](https://deepinfra.com/dash/api_keys) |
| Cerebras | `CEREBRAS_API_KEY` | [Cerebras Cloud](https://cloud.cerebras.ai/) |
| SambaNova | `SAMBANOVA_API_KEY` | [SambaNova Cloud](https://cloud.sambanova.ai/) |
| NVIDIA NIM | `NVIDIA_API_KEY` | [NVIDIA API Catalog](https://build.nvidia.com/) |
| Hugging Face | `HF_TOKEN` | [Hugging Face tokens](https://huggingface.co/settings/tokens) |

Billing and model access are managed by the provider. The public package also
includes the existing Kimi, Muse, Hermes 4 / OpenRouter, and Gemini registrations,
alongside its OpenAI, Claude, GLM, and local model specs. These are connection
options, not a promise that every account can invoke every model.

## Amazon Bedrock: choose the route for your model

AWS offers different APIs and regional model catalogs. See the current
[endpoint comparison](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html)
and [Chat Completions guide](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html).
The direct JNAIQ presets use **Chat Completions**, so select a model whose AWS
card lists that API for the chosen endpoint. A Responses-only model cannot use
this connection.

### Direct Runtime

Choose **Amazon Bedrock · Runtime**, select your AWS region, and copy the exact
model or system inference profile ID from AWS. JNAIQ fills
`https://bedrock-runtime.<region>.amazonaws.com/openai/v1` and the
`AWS_BEARER_TOKEN_BEDROCK` credential slot. Use a Bedrock API key, not an OpenAI
key or an AWS access-key ID. The key's IAM principal still needs invocation
permission, including streaming permission when applicable.

Runtime has **no OpenAI `/models` endpoint**, so model discovery is disabled for
this route. Consult the [AWS model catalog instructions](https://docs.aws.amazon.com/bedrock/latest/userguide/models-get-info.html).
AWS-native catalog commands use AWS credentials; possession of a bearer key
does not establish catalog access. Copying an ID from the console is sufficient
for registration.

### Direct Mantle

Choose **Amazon Bedrock · Mantle** and your AWS region. JNAIQ fills
`https://bedrock-mantle.<region>.api.aws/v1` and the same Bedrock credential slot.
Use **Load available models**, then select a model supporting Chat Completions.
Mantle and Runtime IDs and API support can differ. Changing the region changes
the endpoint; it does not grant model access.

### Converse gateway: Claude, Nova, and other Converse models

1. Save your Bedrock API key in JNAIQ Settings.
2. Double-click **BEDROCK_GATEWAY.bat** on Windows. On macOS, Control-click
   **BEDROCK_GATEWAY.command** and open it. If its executable bit is missing,
   run `bash BEDROCK_GATEWAY.command` in the JNAIQ folder.
3. On first run, paste your Bedrock model or inference profile ID and choose
   the AWS region. For example, a Sonnet 4.5 profile may be
   `us.anthropic.claude-sonnet-4-5-20250929-v1:0`; use the ID available to your
   account. Setup installs pinned LiteLLM 1.103.1 in a separate environment.
4. Keep the gateway window open. In JNAIQ choose **Amazon Bedrock · Converse
   gateway**. Load models or enter **bedrock-chat**, set the context window from
   the AWS model card, and install it. The local gateway key is generated and
   saved automatically; you do not need to copy it.

The gateway binds to `127.0.0.1:4000`; calls are relayed to AWS and incur AWS
charges. Setup performs no inference. It is an optional third-party adapter,
not a native JNAIQ Converse transport. Configurations stay under gitignored
`local_services/bedrock_gateway/`, reference credential slots, and retain the
previous configuration when changed. To change the model, run the launcher
with `--configure`. If port 4000 is occupied, configure with `--port 4001` and
change the JNAIQ Base URL accordingly. Stop the gateway with Ctrl+C.

LiteLLM translates the chat format and drops unsupported optional parameters;
it can change provider sampling semantics. Tool and image support remain
disabled in a generic JNAIQ registration until separately validated. For AWS
SSO/IAM-only installations or a centrally managed proxy, use the general
**LiteLLM gateway** preset and the [provider's authentication guide](https://docs.litellm.ai/docs/providers/bedrock).

## Local models and other providers

- **Ollama:** install [Ollama](https://ollama.com/download), pull the model tag,
  and use Ollama or Ollama's OpenAI-compatible connection. The native catalog
  lists installed tags. No cloud credential is needed.
- **Local servers:** presets cover LM Studio, llama.cpp, vLLM, LocalAI, Jan,
  text-generation-webui, and KoboldCpp. Load a model and start the server in its
  own app first. Check its host/port and model ID. A local credential is optional
  unless that server enables authentication.
- **Gateways:** the general LiteLLM preset can connect Azure, Vertex AI, Cohere,
  Bedrock, and other provider APIs through an existing gateway. Use its model
  alias and save its key as `LITELLM_MASTER_KEY`. Configure upstream credentials
  at the gateway; a cloud key alone does not create a running proxy.
- **Custom / self-hosted:** enter an HTTP(S) Base URL ending in the provider's
  OpenAI-compatible API prefix, its model ID, and a credential slot NAME. After
  registration, the new slot appears in Settings. Paste the actual secret there.

## If setup does not work

- **401 / key missing:** check the selected credential slot and replace an
  expired key. Bedrock short-term API keys expire; save a fresh one.
- **403:** check IAM permission, provider account/model access, and region.
- **404 / unknown model:** compare the exact ID and API support on that endpoint.
- **429:** check provider quotas, balance, and rate limits.
- **Cannot connect to localhost:** start the local server or gateway and check
  its port. A local gateway still uses paid cloud inference upstream.
- **Catalog cannot load:** manual model-ID entry remains available. A catalog
  entry is discovery evidence; a successful invocation establishes actual access.

Provider Health and Usage in JNAIQ show call status and token counts without
copying conversation text into their receipt log.
