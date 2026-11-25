import { useEffect, useRef, useState } from "react";
import { Camera, X } from "lucide-react";

// Barcodes found on things sold in shops: EAN/UPC on packets, Code 128 and 39 on labels, QR on some.
const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "qr_code"];
const SAME_CODE_PAUSE = 2000; // the same item held in view is counted once; pass it away and back for another

let audio;
// A short beep, as a till scanner gives, so the cashier knows without looking.
export function beep(ok = true) {
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    const tone = audio.createOscillator();
    const gain = audio.createGain();
    tone.frequency.value = ok ? 1650 : 320;
    gain.gain.setValueAtTime(0.12, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + (ok ? 0.12 : 0.3));
    tone.connect(gain).connect(audio.destination);
    tone.start();
    tone.stop(audio.currentTime + (ok ? 0.12 : 0.3));
  } catch { /* no sound on this device */ }
}

// The browser's own reader where it has one (Chrome on phones and Macs); elsewhere (Windows and Linux laptops) ZXing.
async function startReading(video, stream, found) {
  if ("BarcodeDetector" in window) {
    try {
      const supported = await window.BarcodeDetector.getSupportedFormats();
      const formats = FORMATS.filter((f) => supported.includes(f));
      if (formats.includes("ean_13")) {
        const detector = new window.BarcodeDetector({ formats });
        let stopped = false;
        const tick = async () => {
          if (stopped) return;
          try {
            if (video.readyState >= 2) (await detector.detect(video)).forEach((code) => found(code.rawValue));
          } catch { /* a frame that could not be read */ }
          setTimeout(() => void tick(), 120);
        };
        void tick();
        return () => { stopped = true; };
      }
    } catch { /* fall back to ZXing */ }
  }
  const [{ BrowserMultiFormatReader }, { BarcodeFormat, DecodeHintType }] = await Promise.all([import("@zxing/browser"), import("@zxing/library")]);
  const hints = new Map([[DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.EAN_13, BarcodeFormat.EAN_8, BarcodeFormat.UPC_A, BarcodeFormat.UPC_E,
    BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.QR_CODE]], [DecodeHintType.TRY_HARDER, true]]);
  const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 100 });
  const controls = await reader.decodeFromStream(stream, video, (result) => { if (result) found(result.getText()); });
  return () => controls.stop();
}

// The laptop's (or phone's) camera as a barcode reader: hold the item's barcode up to it and onCode gets the code.
// It keeps reading until closed, so items are passed in front of it one after another.
export function CameraScanner({ onCode, onClose, hint = "Hold the barcode up to the camera, about a hand's width away." }) {
  const video = useRef(null);
  const last = useRef({ code: "", at: 0 });
  const handler = useRef(onCode);
  useEffect(() => { handler.current = onCode; });
  const [state, setState] = useState("starting");
  const [mirror, setMirror] = useState(true);
  useEffect(() => {
    let stream;
    let stop;
    let closed = false;
    const found = (raw) => {
      const code = String(raw || "").trim();
      const now = Date.now();
      if (!code || (code === last.current.code && now - last.current.at < SAME_CODE_PAUSE)) {
        if (code === last.current.code) last.current.at = now;
        return;
      }
      last.current = { code, at: now };
      handler.current(code);
    };
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera");
        stream = await navigator.mediaDevices.getUserMedia({ audio: false,
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 }, focusMode: { ideal: "continuous" } } });
        if (closed) return;
        // A laptop's camera faces the cashier: show it like a mirror so moving the item left moves it left on screen.
        setMirror(stream.getVideoTracks()[0]?.getSettings?.().facingMode !== "environment");
        video.current.srcObject = stream;
        await video.current.play().catch(() => {});
        stop = await startReading(video.current, stream, found);
        if (closed) stop?.();
        else setState("reading");
      } catch (err) {
        if (!closed) setState(err?.name === "NotAllowedError" ? "denied" : "none");
      }
    })();
    return () => {
      closed = true;
      stop?.();
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  return <div className="cameraScanner" role="region" aria-label="Camera barcode reader">
    <div className="cameraScannerView">
      <video ref={video} muted playsInline className={mirror ? "mirrored" : undefined} />
      {state === "reading" && <span className="cameraScannerAim" aria-hidden="true" />}
      {state === "starting" && <p className="cameraScannerNote"><Camera size={18} aria-hidden="true" /> Opening the camera…</p>}
      {state === "denied" && <p className="cameraScannerNote">The camera is blocked. Allow it for this site (the camera sign in the address bar), then open the camera again.</p>}
      {state === "none" && <p className="cameraScannerNote">No camera was found on this device.</p>}
    </div>
    <div className="cameraScannerFoot">
      <small>{hint}</small>
      {onClose && <button type="button" className="secondary" onClick={onClose}><X size={16} aria-hidden="true" /> Close camera</button>}
    </div>
  </div>;
}
