"""Diagnose the isolated Chromium microphone without touching investigation records."""
from pathlib import Path
import wave
from playwright.sync_api import sync_playwright

fixture = Path('/fixtures/single_speaker_ar.wav')
print('fixture', fixture.exists(), flush=True)
if fixture.exists():
    with wave.open(str(fixture)) as audio:
        print('wave', audio.getparams(), flush=True)
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage',
        '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
        '--use-file-for-fake-audio-capture=' + str(fixture),
        '--unsafely-treat-insecure-origin-as-secure=http://workflow-ui-frontend'])
    page = browser.new_page(permissions=['microphone'], ignore_https_errors=True)
    page.goto('https://workflow-ui-frontend/login')
    print(page.evaluate('''async () => {
      const details = {url: location.href, secure: isSecureContext, mediaDevices: !!navigator.mediaDevices};
      try {
        const stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, channelCount: 1}});
        details.tracks = stream.getTracks().map(t => ({state: t.readyState, settings: t.getSettings()}));
        stream.getTracks().forEach(t => t.stop());
      } catch (e) { details.error = {name: e.name, message: e.message}; }
      return details;
    }'''), flush=True)
    browser.close()
