# Siri Shortcut for Homelab AI access





# Apple Shortcuts flow
Dict:
  text = Dictated Text
  mode = voice
  return_media = true

Get Contents of URL:
  URL: https://siri.yourdomain.com/siri/chat
  Method: POST
  Headers:
    Content-Type: application/json
    X-Harness-Api-Key: your-key
    CF-Access-Client-Id: ...
    CF-Access-Client-Secret: ...
  Body: JSON

Get Dictionary Value: speak
Speak Text
