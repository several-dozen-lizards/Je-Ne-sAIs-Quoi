# JNAIQ setup: new installations, updates, and model connections

For the public **JNAIQ 0.12.1** release. Checked against the published package on September 30, 2026.

JNAIQ keeps your personas, their identity and history, and your house settings on your computer. You choose which model each persona uses. A hosted connection sends the context needed for a reply to that provider; a local model runs through a server on your computer.

**New to JNAIQ?** Start with [Install JNAIQ](#1-install-jnaiq-new-users).

**Already have a household?** Start with [Update your existing installation](#2-update-your-existing-installation-current-users). You can keep your personas and add a different model to their rosters.

**Already on 0.12.1?** Go straight to [Choose your model connection](#3-choose-your-model-connection).

[Download JNAIQ](https://github.com/several-dozen-lizards/Je-Ne-sAIs-Quoi/archive/refs/heads/main.zip) · [Public repository](https://github.com/several-dozen-lizards/Je-Ne-sAIs-Quoi) · [Full provider reference](https://github.com/several-dozen-lizards/Je-Ne-sAIs-Quoi/blob/main/docs/MODEL_SETUP.md)

## 1. Install JNAIQ (new users)

### Windows

1. Download the ZIP above. Right-click it and choose **Extract All**.
2. Put the extracted JNAIQ folder somewhere you want to keep it. Open the folder containing `INSTALL_JNAIQ.bat`; run the files from that folder, outside the ZIP.
3. Double-click **INSTALL_JNAIQ.bat**. Follow the prompts. If a compatible Python installation is missing, setup can offer to install Python 3.12 for your Windows user.
4. Let setup finish downloading and checking its dependencies. It creates JNAIQ's own environment and asks you to name the local owner of the house.
5. If setup offers to start JNAIQ, accept. Otherwise double-click **START_NEXUS.bat**.

If installation is interrupted, run `INSTALL_JNAIQ.bat` again. It reuses the installation and leaves an existing local owner and personas in place.

### macOS

1. Install **Python 3.12** from the [official Python downloads for macOS](https://www.python.org/downloads/macos/). The shipped Mac installer supports Python 3.10–3.12.
2. Download and extract JNAIQ. Open the folder containing `INSTALL_JNAIQ.command`.
3. Control-click **INSTALL_JNAIQ.command**, choose **Open**, and follow the prompts. Setup creates its own environment and asks you to name the local owner.
4. Start the house with **START_NEXUS.command** if setup has not already opened it.

If the installer will not execute after extraction, open Terminal in the JNAIQ folder and run:

```bash
bash INSTALL_JNAIQ.command
```

The installer repairs the Mac launchers' executable permissions. Run it again if dependency installation was interrupted.

**Ready to continue:** the JNAIQ household window opens. You can save a provider key before creating a persona or registering a model.

## 2. Update your existing installation (current users)

Use the updater **inside your existing JNAIQ folder**. This keeps the update attached to the house you already use.

1. Finish the current conversation turn. Close JNAIQ's owned app window, or run **STOP_NEXUS.bat** on Windows / **STOP_NEXUS.command** on macOS. Let shutdown finish. If the launcher opened a regular browser tab rather than an owned window, use the Stop launcher to end the session.
2. For a rollback copy, copy the stopped installation folder to a separate backup location.
3. Run **UPDATE_JNAIQ.bat** on Windows or **UPDATE_JNAIQ.command** on macOS. Follow its prompts and wait for it to finish.
4. Start JNAIQ again with **START_NEXUS.bat** / **START_NEXUS.command**.
5. Check that your existing household appears. The folder's plain-text `VERSION` file identifies the installed release; this guide covers `0.12.1`.

If a Mac update launcher will not execute, run this in Terminal from the existing JNAIQ folder:

```bash
bash UPDATE_JNAIQ.command
```

The updater replaces managed application files while preserving local keys, owner settings, personas, history, drafts, world state, local-service configuration, and existing environments. A separate custom model file was also preserved in the 0.12.0 → 0.12.1 update check. Keep a backup of your own changes to shipped application or model files: those are managed files and may be replaced during an update.

You can continue using your current model. To try another one, register its connection below, then add it to the existing persona's roster in [Select the model](#5-select-the-model-and-check-the-connection).

If an older installation still uses `UPDATE_JNSQ` launchers, use its existing platform updater. The public migration brings forward the JNAIQ launchers and local identity files.

## 3. Choose your model connection

| You want to use… | What you need | Where to go |
| --- | --- | --- |
| A model running on your computer | Ollama, or another running local model server | [Local models](#local-models) |
| A hosted provider such as Anthropic, OpenAI, Gemini, Kimi, or OpenRouter | That provider's API access and key | [Hosted providers](#hosted-providers) |
| Claude, Nova, or another Converse model through Amazon Bedrock | AWS Bedrock access, a Bedrock API key, and the optional gateway | [Bedrock Converse gateway](#a-converse-gateway-for-claude-nova-and-other-converse-models) |
| A Bedrock model supporting Chat Completions | AWS Bedrock access and a Bedrock API key | [Bedrock Runtime or Mantle](#b-direct-runtime-chat-completions) |
| An existing company or personal gateway | Its URL, model alias, and any gateway key | [Other servers and gateways](#other-servers-and-gateways) |

**“Install a model” registers a connection in JNAIQ.** It does not download local model weights, start a local server, or make a test inference call. Those are separate steps. A registration is available to the whole household; selecting it for a persona is a separate choice.

### Hosted providers

1. Obtain an API key from your provider's own account or developer console. Check that the account has access and billing for the model you want.
2. Start JNAIQ and open **Settings → API keys**. Find the provider's slot, paste the key, and save.
3. Open **Household → Install a model**.
4. For direct Anthropic access, choose **Anthropic API**. For other hosted providers, choose **OpenAI-compatible · hosted or local**, then choose the provider.
5. Click **Load available models**, then choose an ID. If discovery is unavailable, enter the exact ID in **Other model ID** from the provider's model documentation.
6. Give the connection a short **JNAIQ model name**, such as `my-cloud-model`. Use **Context window · tokens** to enter the model's documented context capacity when registering an unfamiliar model. This is the size of its context, rather than just the length of its reply.
7. Click **Install model**. Then [select it for a persona](#5-select-the-model-and-check-the-connection).

For a model already included in JNAIQ, you can choose that installed registration directly when creating a persona or adding to a roster. Existing registrations carry their own declared connection and sampling settings.

Some common key slots are:

| Provider | Slot in Settings |
| --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` |
| Amazon Bedrock | `AWS_BEARER_TOKEN_BEDROCK` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Kimi / Moonshot | `MOONSHOT_API_KEY` |
| Meta Model API / Muse | `MODEL_API_KEY` |
| Z.AI / GLM | `ZAI_API_KEY` |

The [full provider reference](https://github.com/several-dozen-lizards/Je-Ne-sAIs-Quoi/blob/main/docs/MODEL_SETUP.md#hosted-provider-presets) also covers Together, Groq, Mistral, DeepSeek, xAI, Fireworks, DeepInfra, Cerebras, SambaNova, NVIDIA NIM, and Hugging Face.

**Credential slot name** means a name such as `OPENAI_API_KEY`. Put the actual secret in **Settings → API keys**. Keys are stored in your local `.env`; registered model files refer to the slot name.

### Local models

For Ollama:

1. Install and open [Ollama](https://ollama.com/download).
2. Download a model using Ollama. For the public package's example tag, open PowerShell or Terminal and run:

```text
ollama pull llama3.1:8b
```

3. Wait for the download to finish. Keep Ollama available while using the model.
4. In JNAIQ, open **Household → Install a model** and choose **Ollama · local**.
5. Click **Load available models** and select the downloaded tag, or enter its exact tag manually. Name the connection and install it.
6. [Select it for a persona](#5-select-the-model-and-check-the-connection).

Local models need enough memory and storage for the model you choose. The tag above is an example; you can use another installed tag that suits your computer. See [Ollama's quickstart](https://docs.ollama.com/quickstart) for its own setup.

### Other servers and gateways

For **LM Studio, llama.cpp, vLLM, LocalAI, Jan, text-generation-webui, or KoboldCpp**, load a model and start that application's compatible API server first. In JNAIQ choose **OpenAI-compatible · hosted or local** and the matching provider preset. Check **Base URL** against the server's actual address and port, then load its models or enter its model ID.

For an existing **LiteLLM gateway**, select that preset and use its model alias. Save its gateway key under `LITELLM_MASTER_KEY`. Upstream provider credentials belong in the gateway's configuration. This route can also connect providers such as Azure, Vertex AI, or Cohere through a configured proxy.

For **Custom / self-hosted**, enter the compatible API's Base URL and model ID. If it needs authentication, enter a credential slot name; after registration, save the secret in the new Settings slot. A local server can still relay to a paid cloud provider, so check what the server is configured to use.

## 4. Set up Amazon Bedrock

### Get your AWS details first

You need an AWS account with Bedrock access, an **AWS region**, and the **exact model or inference profile ID** available to that account.

In the [Amazon Bedrock console](https://console.aws.amazon.com/bedrock), select your region and open **API keys**. AWS documents short-term keys that expire with the console session, up to 12 hours, and long-term keys with a configured expiry. Follow [AWS's API-key instructions](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) for the appropriate key type.

Save the Bedrock API key in **Settings → API keys → `AWS_BEARER_TOKEN_BEDROCK`**. Use the Bedrock bearer key here; an AWS access-key ID is a different credential.

A valid key still needs the appropriate model permissions. Starting a persona and sending messages can incur AWS charges. Model registration and the gateway's initial setup do not perform inference.

Choose one of the routes below using the model's AWS API support. The direct presets use Chat Completions; the gateway translates JNAIQ's chat requests to Converse. [AWS's endpoint comparison](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html) explains the differences.

### A. Converse gateway for Claude, Nova, and other Converse models

This is the public 0.12.1 route for a model you want to use through **Converse**.

1. Install or update JNAIQ and save the Bedrock key as described above.
2. In the JNAIQ folder, double-click **BEDROCK_GATEWAY.bat** on Windows, or open **BEDROCK_GATEWAY.command** on macOS. If the Mac launcher will not execute, run `bash BEDROCK_GATEWAY.command` from that folder.
3. On first run, enter the model or inference profile ID and your AWS region. Copy the ID from AWS. The release check used Sonnet 4.5 with `us.anthropic.claude-sonnet-4-5-20250929-v1:0` in `us-east-1`; that is an example, and your account may have different models or profiles.
4. Wait for gateway setup and startup to finish. It installs its dependencies in a separate local environment. **Keep the gateway window open.**
5. In JNAIQ, open **Household → Install a model**. Choose **OpenAI-compatible · hosted or local**, then **Amazon Bedrock · Converse gateway**.
6. Leave the default **Base URL** at `http://127.0.0.1:4000/v1`. The preset uses the automatically generated local gateway key.
7. Click **Load available models** and select **bedrock-chat**, or type `bedrock-chat` in **Other model ID**. This is the gateway's local alias; you entered the AWS ID during gateway setup.
8. Give the connection a JNAIQ name, enter the upstream model's documented context window, and click **Install model**.
9. [Select it for a persona and check a reply](#5-select-the-model-and-check-the-connection).

For later sessions, launch `BEDROCK_GATEWAY` again and keep it open while using that connection. It reuses the saved configuration. Stop the gateway with **Ctrl+C** in its window when you finish. After replacing an expired AWS key in Settings, restart the gateway so it loads the new value.

To change the upstream model or region, run the launcher with `--configure` from the JNAIQ folder:

```powershell
# Windows PowerShell
.\BEDROCK_GATEWAY.bat --configure
```

```bash
# macOS Terminal
bash BEDROCK_GATEWAY.command --configure
```

The gateway's settings and environment live under `local_services/bedrock_gateway/`. Changing its upstream model changes what its `bedrock-chat` alias points to. Check the context window of any JNAIQ registration using that alias when you change models.

### B. Direct Runtime: Chat Completions

1. Save your Bedrock key in Settings.
2. Open **Household → Install a model**. Choose **OpenAI-compatible · hosted or local**, then **Amazon Bedrock · Runtime**.
3. Enter your **AWS region**. JNAIQ fills `https://bedrock-runtime.<region>.amazonaws.com/openai/v1`.
4. Enter the exact model or supported inference profile ID in **Other model ID**. Choose a model whose AWS card lists **Chat Completions** on Runtime.
5. Name the connection, supply its documented context window, and install it. Then [select it for a persona](#5-select-the-model-and-check-the-connection).

**Load available models is disabled for Runtime.** AWS's Runtime endpoint does not implement the compatible `/models` operation. Copy the ID from the console or [AWS model catalog](https://docs.aws.amazon.com/bedrock/latest/userguide/models-get-info.html). This is expected behavior. See [AWS's Chat Completions instructions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html).

### C. Direct Mantle: Chat Completions

1. Save your Bedrock key in Settings.
2. Choose **OpenAI-compatible · hosted or local → Amazon Bedrock · Mantle** in **Install a model**.
3. Enter your **AWS region**. JNAIQ fills `https://bedrock-mantle.<region>.api.aws/v1`.
4. Click **Load available models** and select a model that supports **Chat Completions** on Mantle. You can also enter its exact ID manually.
5. Name the connection, set its documented context window, and install it. Then [select it for a persona](#5-select-the-model-and-check-the-connection).

Mantle and Runtime can expose different IDs and API support. Check the model against the chosen endpoint; a model supporting only Responses cannot use JNAIQ 0.12.1's Chat Completions connection. [AWS documents the two Chat Completions routes here](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html).

## 5. Select the model and check the connection

### For your first persona

1. Open **Household → Create a persona**.
2. Give them a name, choose the registered model and an interior preset, and create them.
3. Use the voice editor to describe their voice, values, relationships, and boundaries. Here, “voice” means their written identity and manner of speaking.
4. Select their model on the household card and click **start selected**. Open their conversation.

### For an existing persona

1. On their household card, click **+ model**.
2. Choose the installed connection and click **Add to roster**.
3. Select it in the card's model dropdown.
4. Click **switch / restart** if they are running, or **start selected** if they are stopped.

Adding a model to the roster alone leaves the current model selected. When you switch, the persona keeps their local identity and history; the selected model becomes the connection used to generate their replies.

### Check a real reply

Send a short greeting in the persona's conversation. A completed reply confirms text inference works with that connection. Opening JNAIQ, registering a model, or loading a catalog confirms earlier setup steps; the reply checks the actual call.

Open **Usage** to review provider call status and any reported token usage. Missing usage information means the provider did not report it. Text success alone does not establish tool or image support; generic new registrations begin with conservative capabilities.

## 6. When something does not connect

| What you see | What to check next |
| --- | --- |
| Missing key or a 401 error | Save the key in the selected Settings slot. Replace expired keys. For Bedrock's gateway, restart it after changing the AWS key. |
| A 403 error | Check account/model access and permissions. For Bedrock, also check the region and the inference target. |
| A 404 or unknown-model error | Compare the exact model ID, Base URL, and API support. Use `bedrock-chat` in the gateway connection; use an AWS ID in the direct routes. |
| A 429 error | Check the provider's rate limits, quota, and account balance. |
| “Cannot connect” to a local address | Start Ollama, the local model server, or the Bedrock gateway and check its port. |
| The catalog will not load | Enter an exact model ID manually. Runtime's disabled catalog button is expected. |
| The model is registered but a persona uses the old one | Add the connection with **+ model**, select it, then use **switch / restart** or **start selected**. |
| Installation stopped before completion | Rerun the platform's installer and read the error shown in its window. |

If port 4000 is occupied, stop the Bedrock gateway and configure another port, for example:

```powershell
# Windows PowerShell, in the JNAIQ folder
.\BEDROCK_GATEWAY.bat --configure --port 4001
```

```bash
# macOS Terminal, in the JNAIQ folder
bash BEDROCK_GATEWAY.command --configure --port 4001
```

Use `http://127.0.0.1:4001/v1` as the JNAIQ connection's Base URL. Other gateway connections using the old port will need the same adjustment.

When asking for help, include your JNAIQ version, operating system, provider/connection type, model ID, and the displayed error. Keep API keys out of screenshots and messages.

## What was checked for this release

The published 0.12.1 package passed a fresh Windows installation, an actual public 0.12.0 → 0.12.1 update preserving saved local files, and live ordinary and streaming Bedrock text calls through the optional Converse gateway. The anonymous public download was checked against the reviewed files and manifest.

Mac launchers are included, but installation and live gateway execution have not been tested on a Mac. Model availability and access depend on each provider and account; the release checks do not establish every provider's tool, image, or model capabilities.
