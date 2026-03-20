/**
 * AudioWorkletProcessor for recording microphone input as PCM 16-bit mono.
 *
 * Receives Float32 audio from the mic (typically 44.1/48 kHz), downsamples
 * to 16 kHz, converts to Int16 PCM, and posts the raw bytes to the main thread.
 *
 * Messages from the main thread:
 *   { command: "start" }  — begin capturing
 *   { command: "stop" }   — stop capturing
 *
 * Messages to the main thread:
 *   { type: "audio", data: Int16Array }  — a chunk of 16 kHz PCM audio
 */

class PCMRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._recording = false;
    this._bufferSize = 2048; // samples at source rate before flushing
    this._buffer = [];

    this.port.onmessage = (event) => {
      if (event.data.command === "start") {
        this._recording = true;
        this._buffer = [];
      } else if (event.data.command === "stop") {
        // Flush remaining buffer
        if (this._buffer.length > 0) {
          this._flush();
        }
        this._recording = false;
      }
    };
  }

  /**
   * Downsample Float32 audio from sourceSampleRate to 16000 Hz.
   * Simple linear interpolation — good enough for voice.
   */
  _downsample(float32Array, sourceSampleRate) {
    if (sourceSampleRate === 16000) {
      return float32Array;
    }

    const ratio = sourceSampleRate / 16000;
    const newLength = Math.round(float32Array.length / ratio);
    const result = new Float32Array(newLength);

    for (let i = 0; i < newLength; i++) {
      const srcIndex = i * ratio;
      const lower = Math.floor(srcIndex);
      const upper = Math.min(Math.ceil(srcIndex), float32Array.length - 1);
      const frac = srcIndex - lower;
      result[i] = float32Array[lower] * (1 - frac) + float32Array[upper] * frac;
    }

    return result;
  }

  /**
   * Convert Float32 samples [-1, 1] to Int16 PCM.
   */
  _floatToInt16(float32Array) {
    const int16 = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
  }

  /**
   * Flush accumulated buffer: downsample → convert → post to main thread.
   */
  _flush() {
    const float32 = new Float32Array(this._buffer);
    this._buffer = [];

    const downsampled = this._downsample(float32, sampleRate); // sampleRate is a global in AudioWorklet
    const pcm16 = this._floatToInt16(downsampled);

    this.port.postMessage(
      { type: "audio", data: pcm16.buffer },
      [pcm16.buffer] // Transfer ownership for zero-copy
    );
  }

  process(inputs, outputs, parameters) {
    if (!this._recording) {
      return true; // Keep processor alive
    }

    const input = inputs[0];
    if (!input || !input[0]) {
      return true;
    }

    // Take channel 0 (mono)
    const channelData = input[0];
    for (let i = 0; i < channelData.length; i++) {
      this._buffer.push(channelData[i]);
    }

    // Flush when we've accumulated enough samples
    if (this._buffer.length >= this._bufferSize) {
      this._flush();
    }

    return true; // Keep processor alive
  }
}

registerProcessor("pcm-recorder-processor", PCMRecorderProcessor);
