# LLM 官方分词器

token 计数按三档走：**本目录里的官方词表 > tiktoken 的官方模型映射 > `cl100k_base` 兜底**。
兜底档对中文会多算（159 条真实消息实测：比 DeepSeek 官方多 47.8%、比 Qwen3.5 官方多 42.7%），
且完全不含 chat 模板开销（本机单消息请求实测正文 7、整条请求 59），所以只在没有官方词表时用；
计费以响应里的 `usage` 为准，不吃这些估算。

词表文件体积大且不入库（与 `internal/core/ltp/` 同口径）。缺失时该模型自动落到兜底档，
不影响功能，只是数不准。

## deepseek/

来源：DeepSeek 官方发布的 `tokenizer.json` + `tokenizer_config.json`（128k 词表 BPE）。

```bash
# 国内走 hf-mirror
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download deepseek-ai/DeepSeek-V3 \
  tokenizer.json tokenizer_config.json \
  --local-dir internal/core/language_model/tokenizers/deepseek
```

放好后自检：`encode("Hello!")` 必须是 `[19923, 3]`（加载器里已内置这条断言，
不符则该模型视为无官方词表，落到兜底档）。

> 注意：不要用官方脚本里的 `AutoTokenizer.from_pretrained(目录)`。在 transformers 5.16 下
> 它按 `tokenizer_class=LlamaTokenizer` 解析成**慢速**分词器，对中文会静默返回 0 个 token。
> 代码走 `PreTrainedTokenizerFast(tokenizer_file=...)`，输出与官方脚本逐位一致。

## qwen35/

Qwen3.5 / 3.6 / 3.8 一系（`tokenizer.ggml.pre = qwen35`，词表 248,044 + 276 个控制符）。
**与 Qwen3 系（151,643）不同族，不能混用。**

```bash
curl -sL https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main/tokenizer.json -o qwen35/tokenizer.json
curl -sL https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main/tokenizer_config.json -o qwen35/tokenizer_config.json
```

> `hf download` / `huggingface_hub` 在这台机上取这类文件会报 `LocalEntryNotFoundError`
> （新版走 xet 存储，hf-mirror 不代理），直接用 resolve 链接即可。
> 另外 `system_config` 里 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 会强制离线。

接上后与服务端对过表：本机 `qwen/qwen3.8-27b` 的 GGUF 元数据 `chat_template` 长 8952，
与 `tokenizer_config.json` 里的完全一致。整条请求口径（模板 + 正文）实测与服务端逐位相同：
单条消息 **59 == 59**；四条多轮消息（system/user/assistant/user）**93 == 93**，
而只算正文是 29 —— 短对话会少算 3.2 倍，所以计数走模板口径（`count_chat_tokens_for_model`）。

> 代价：模板口径比正文口径每次多约 25ms（241 条消息实测 66ms vs 41ms）。
> 历史裁剪是逐条 pop 再重算，最坏情况会把这点开销乘上迭代次数。

