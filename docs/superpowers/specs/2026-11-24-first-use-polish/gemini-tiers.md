# Gemini API: what a key's tier allows (research, 2026-11-24)

All pages below were opened on 2026-11-24. The Gemini API docs at ai.google.dev now 301-redirect to aistudio.google.com/docs (for example ai.google.dev/gemini-api/docs/rate-limits -> aistudio.google.com/docs/rate-limits, ai.google.dev/api/models -> aistudio.google.com/api-reference/models). None of the AI Studio doc pages I opened shows a "last updated" date except the per-model pages. WebFetch summarizes pages, so quotes are close paraphrase unless in quotation marks.

## Direct answer: how can the app tell what a key's tier allows?

There is no API call that reports a key's tier, its per-model limits, or whether a model is usable by that key.

- `models.list` / `models.get` return no tier, quota or availability field, and the reference does not say the list is filtered by the caller's access. The official troubleshooting page says a 200 from `models.list` does not confirm that inference is enabled for the project.
- No rate-limit response headers are documented. The only documented header is `x-gemini-service-tier` (which service tier, Priority or Standard, served a request), not the billing tier.
- The tier is a per-project (billing) property, shown to a human on the AI Studio Projects page (Billing Tier column: Free, Tier 1, Tier 2, Tier 3) and limits on the AI Studio rate-limit page.
- Per-model free-tier availability is documented only in prose: the pricing page and each model page say "Free of charge" or "Not available" on the free tier.

So the app can only (a) ship or fetch a static map of which models have a free tier (from the pricing page), and/or (b) probe: send a minimal request to the chosen model and classify the result (200 = usable; 403/400 failed_precondition/402/429 with a `limit: 0` style quota = not usable on this project/tier; 503/500 = transient capacity, retry later, says nothing about the tier). The probe costs a request against the quota.

## 1. Does Google AI Pro / Ultra change the API tier? What moves a project to paid?

- **No.** "Google AI plans for AI Studio are separate from Gemini API usage tiers." The plan's daily quota "applies only within the Google AI Studio web interface."
  Source: https://aistudio.google.com/docs/google-ai-plans (redirected from ai.google.dev/gemini-api/docs/google-ai-plans). No date shown. Official doc.
- **Credit today:** the subscription includes monthly Google Cloud credits that apply to paid API keys: AI Pro $10/month; AI Ultra $40/month (Ultra 5x) or $100/month (Ultra 20x); each grant lasts 12 months. "Claimed Google Cloud credits apply to Gemini API requests made with a paid API key." To claim: "Claim free API credits" in AI Studio's left menu, choose a project/key, set up Cloud Billing (Prepay needs a $5 minimum deposit and a balance above $0), accept the Developer Program terms, link the paid key. Requires the same @gmail.com account as the subscription. So the credits do nothing for a Free Tier project until billing is set up.
  Same source. Official doc.
- **What moves a project off Free:**
  - Free: active project; some projects need verification.
  - Tier 1: link an active billing account (cap $250). AI Studio's flow: "linking a billing account and prepaying to add a minimum of $5".
  - Tier 2: $100 paid in total + 3 days since first successful payment (cap $2,000).
  - Tier 3: $1,000 paid + 30 days (cap $20,000 to $100,000+).
  - Upgrade is automatic once criteria are met; Free -> Tier 1 typically instant, later upgrades within 10 minutes. "Rate limits are applied per project, not per API key."
  Sources: https://aistudio.google.com/docs/rate-limits (official doc, no date); https://aistudio.google.com/docs/billing (official doc, no date; also says new users default to Prepay and get HTTP 402 when the balance hits $0, and that the Cloud Welcome credit cannot pay for AI Studio usage for accounts opened after 2026-03-02). Note: the billing page says tiers are set per billing account while the rate-limits page says limits apply per project; I did not resolve that wording difference.
- Third party / not used: blog.google posts about AI Pro developer benefits appeared in search but I did not open them.

## 2. Is there an API that reports tier, limits or usability?

- **Model resource fields** (`models.list`, `models.get`): name, baseModelId, version, displayName, description, inputTokenLimit, outputTokenLimit, supportedGenerationMethods, thinking, temperature, maxTemperature, topP, topK. No tier, availability, quota or rate-limit field. The method "Lists the Models available through the Gemini API" with no statement that it is filtered by caller access.
  Source: https://aistudio.google.com/api-reference/models (redirected from ai.google.dev/api/models). No date. Official doc.
- "A `200 OK` from `models.list` doesn't confirm that inference calls are enabled for the project." Source: https://aistudio.google.com/docs/troubleshooting. No date. Official doc.
- **Headers:** no rate-limit headers documented on the rate-limits or api-errors pages. The priority-inference page documents `x-gemini-service-tier` (shows a downgrade from priority to `standard`); that is the service tier, not Free/Tier 1-3. Source: https://aistudio.google.com/docs/priority-inference. No date. Official doc.
  A forum reply (user Susarla_Sai_Manoj, 2024-10-01, no staff badge shown) says "Currently, Gemini does not provide response headers for rate limit information." https://discuss.ai.google.dev/t/where-how-do-i-find-remaining-tokens-requests-count-after-making-a-request/41117. Forum, staff status not confirmed; old.
- **Cloud Quotas API:** needs IAM permissions on the project (Cloud Quotas Admin, `cloudquotas.quotas.get`, etc.). Source: https://docs.cloud.google.com/docs/quotas/api-overview (no date, official doc). The page does not name the auth method; since it is IAM-gated, my inference is that an AI Studio API key alone cannot call it (needs an OAuth user or service account). Not verified by a call.
- **Where a human sees it:** AI Studio Projects page, Billing Tier column (https://aistudio.google.com/projects); active limits at https://aistudio.google.com/rate-limit; usage at https://aistudio.google.com/usage. Sources: rate-limits and billing pages above.

## 3. Is `models.list` filtered by tier? Which models are paid-only? What error?

- **Filtering:** not documented either way. The reference does not say it filters; troubleshooting says listing does not prove inference works. A forum reply suggests listing models "to see if [a model] is even available for your API key" (https://discuss.ai.google.dev, search snippet only, not opened; third party). I could not verify whether a free-tier key sees paid-only models in the list. To settle: call `models.list` with a Free Tier key and check whether `gemini-4-argon` appears (the user's key apparently could call argon and got 503, which suggests it is listed and routed).
- **Paid-only (free tier "Not available")** per https://aistudio.google.com/docs/pricing (official doc, no date): gemini-4-argon, gemini-4-carbon, gemini-4-neon, gemini-3.1-pro-preview. Also gemini-omni-1.2-flash and genie-4 (rate-limits page). Free of charge on the free tier: gemini-4-hydrogen, gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite. The page was 118k characters; I read it in two parts, but my model checks were limited to the models named here.
- **Error for a free-tier key on a paid-only model:** not documented. The api-errors page lists 400 `failed_precondition` (e.g. billing disabled), 403 `permission_denied` (key lacks permission, or project restricted / needs verification or billing), 402 `payment_required` (Prepay balance at 0), 429 `rate_limit_exceeded` / `quota_exceeded`, 404 `model_not_found`. Source: https://aistudio.google.com/docs/api-errors (official doc, no date). Forum reports (third party) show 429 RESOURCE_EXHAUSTED with "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: ..." when a model has no free quota (search snippets from discuss.ai.google.dev, threads 114215 and 116437; not opened, older models). I could not verify which code a free-tier key gets today for gemini-4-argon; the user's own observation was 503, not 403/429.

## 4. 503 "experiencing high demand"

- Official: 503 `service_unavailable` = "temporarily overloaded or down"; wait and retry with exponential backoff. https://aistudio.google.com/docs/api-errors (official doc).
- Official: retry only 408, 429 and 5xx, with exponential backoff and jitter and a max retry count (Python SDK retries up to 4 times, ~1s start, 60s cap). Do not retry 400, 402, 403. The page does not recommend switching models. https://aistudio.google.com/docs/troubleshooting (official doc).
- 429 differs: it is your project's limit (RPM/TPM/RPD or spend cap; `quota_exceeded` = daily quota; spend-limit exceedance returns `429 RESOURCE_EXHAUSTED`). 503 is server capacity. Sources: api-errors, rate-limits.
- Forum (discuss.ai.google.dev/t/handling-429-503-errors-from-the-gemini-api/124640, first post by Jon_Matthews, 2026-02-20; forum staff elsewhere refer to it as their pinned guidance, but the page shows no staff badge): "503 errors are unrelated to your quota"; backoff and retry, move non-realtime work to the Batch API; 429s now carry a description field naming the cause (tier drop, depleted prepay, spend cap, rate limit).
- Free vs paid / preview: no official statement that free-tier traffic gets 503 more often. The priority-inference page says Priority is "strictly non-sheddable", Flex is "Best-effort (Sheddable)", Standard gets overflow from Priority; it does not say how free-tier traffic is treated. Forum threads (third party) report the exact "high demand" message on paid Tier 2/3 projects and on stable and preview models alike, often with no staff reply: https://discuss.ai.google.dev/t/503-this-model-is-currently-experiencing-high-demand-spikes-in-demand-are-usually-temporary-please-try-again-later/138664 (opened; first post 2026-04-08, no staff reply visible).
- Consequence for the app: the 503 on argon and hydrogen says nothing about the key's tier. Hydrogen is free-tier eligible, so a 503 there is capacity, not entitlement.

## 5. gemini-4-hydrogen and gemini-4-argon

- Both are on the official models page https://aistudio.google.com/docs/models (official doc, no date). The page recommends Gemini 4 Hydrogen or 3.5 Flash-Lite for new projects.
- `gemini-4-hydrogen`: Stable ("Stable: gemini-4-hydrogen"); free tier: input and output free of charge on Standard; Search/Maps grounding not free; 1,048,576-token context, 65,536 default max output. Latest update November 2026. https://aistudio.google.com/docs/models/gemini-4-hydrogen. Official doc.
- `gemini-4-argon`: Stable; free tier Not available, all tokens billed; same context and output limits. Last updated October 2026. https://aistudio.google.com/docs/models/gemini-4-argon. Official doc.
- Stable text models labeled Stable on the models page: `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, plus the Gemini 4 family (`gemini-4-hydrogen`, `gemini-4-argon`; `gemini-4-carbon` and `gemini-4-neon` were not labeled on the index and I did not open their pages). Deprecated: `gemini-2.5-flash`, `gemini-2.5-pro`. Shut down: `gemini-2.0-flash`, `gemini-2.0-flash-lite`, `gemini-3-pro-preview`, `gemini-3.1-flash-lite-preview`.

## 6. Interactions API

- GA: "As of June 2026, it is Generally Available and the recommended interface for all new projects." Supported Gemini models: 4 Carbon, 4 Argon, 4 Neon, 4 Hydrogen, 3.8 Flash, 3.6 Flash, 3.1 Pro Preview, 3.5 Flash-Lite, 3.1 Flash-Lite, 3 Flash Preview, 2.5 Pro, 2.5 Flash, 2.5 Flash-Lite, 3 Pro Image, 3.1 Flash Image, 3.1 Flash TTS Preview; plus Gemma 4 31B IT, Gemma 4 26B MoE IT, Lyria models, and Deep Research / Antigravity preview agents. https://aistudio.google.com/docs/interactions. Official doc, no date.
- Free tier: not stated directly; the page says "Free Tier: The system retains interactions for 1 day", which implies free-tier use is supported.
- `store=false` opts out of storage; incompatible with background execution and with `previous_interaction_id`.
- No `models.list` field or `supportedGenerationMethods` value for Interactions is documented (the Model reference lists only `generateMessage`/`generateContent` as examples). Unverified whether the live list returns another method name; check by printing `supportedGenerationMethods` from a real `models.list` call.

## 7. Pages for the user

- Create a key: https://aistudio.google.com/apikey (also https://aistudio.google.com/api-keys). Source: https://aistudio.google.com/docs/api-key (official doc).
- Tier: https://aistudio.google.com/projects (Billing Tier column). Source: billing page.
- Rate limits: https://aistudio.google.com/rate-limit. Usage: https://aistudio.google.com/usage.
- Claim AI Pro/Ultra API credits: "Claim free API credits" in AI Studio's left menu (google-ai-plans page; no URL given).
- Paid-tier limit increase form linked from the rate-limits page: https://forms.gle/ETzX94k8jf7iSotH9 (not opened).

## Not verified

- Whether `models.list` for a Free Tier key includes paid-only models (needs a live call).
- The exact status and message a Free Tier key gets today for a paid-only model such as gemini-4-argon (needs a live call when argon is not overloaded).
- Whether free-tier traffic is shed before paid under load (no official statement found).
- Whether Interactions support appears as a `supportedGenerationMethods` value.
- Whether Cloud Quotas API accepts an API key (inferred no from its IAM requirements).
- Blog posts on AI Pro developer benefits and the Google Developer Program FAQ were not opened.
