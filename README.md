# omlx-prompt-shrink

OpenCode için **oMLX / Qwen** context sınırı yönetimi MCP server’ı.

## Problem

`Qwen3.6-35B-A3B-4bit` (oMLX üzerinden) 32.768 token context ile çalışırken:

```text
Prompt is too long: 39514 tokens > 32768 maximum context length
```

Uzun prompt veya history yığılınca bu hata agent çalışmasını durdurur.

## Çözüm

Bu MCP server iki tool ile çalışır:

- `estimate_context` — verilen mesaj listesinin yaklaşık token sayısını hesaplar ve
  context aşımını söyler.
- `trim_context` — context aşımı varsa en eski mesajları budar ve yeni mesaj listesini
  döner.

Token tahmini yaklaşık olmalıdır: karakter sayısının 4 ile bölünmesi. Kesin tokenizer
yerine basit tahmin kullanılır.

Varsayılanlar:

- `max_context_tokens`: `32768`
- `keep_last`: `8`

## OpenCode’da kurulum

1. `server.py` dosyasını projenize veya kendi dizinine kopyalayın.
2. Python ortamında MCP SDK kurun:

```bash
pip install mcp
```

3. OpenCode desktop / CLI yapılandırmasında `mcp` altına local sunucu ekleyin:

```jsonc
{
  "mcp": {
    "omlx-prompt-shrink": {
      "type": "local",
      "enabled": true,
      "command": [
        "python3",
        "/absolute/path/to/omlx_prompt_shrink.py"
      ],
      "timeout": 60000
    }
  }
}
```

4. OpenCode’u restart edin.
5. Model olarak `Qwen3.6-35B-A3B-4bit` / oMLX seçin.

## Kullanım

- `estimate_context` çağrısı ile mevcut context tahmini alın.
- `should_trim` `true` dönerse `trim_context` çağrılarak history budanır.
- Agent, uzun prompt geldiğinde bu tool’ları kullanarak context’i sınır altına alabilir.

```json
{
  "messages": [
    { "role": "user", "content": "Birinci mesaj" },
    { "role": "assistant", "content": "Birinci cevap" },
    { "role": "user", "content": "İkinci mesaj" }
  ],
  "keep_last": 8,
  "max_context_tokens": 32768
}
```

## Not

- Context limit: `32768` token.
- Trim politikası: en eski mesajları budar, `keep_last` sayısı kadar son mesajı korur.
- Bu server, oMLX dışındaki MCP istemcilerle de çalışabilir; araç arayüzü MCP standartıdır.

## License

Bu repository MIT License ile açılabilir. (Opsiyonel — kullanıcı kararı.)
