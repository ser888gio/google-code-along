/**
 * AudioWorkletProcessor for playing back PCM audio received from the server.
 *
 * Uses a ring buffer to handle asynchronous audio chunk delivery.
 * Expects 24 kHz, 16-bit mono PCM input (converted to Float32 for playback).
 *
 * Messages from the main thread:
 *   { command: "play", data: ArrayBuffer }  — enqueue PCM chunk for playback
 *   { command: "stop" }                     — clear buffer, stop playback
 *
 * Messages to the main thread:
 *   { type: "playback_complete" }  — ring buffer has been fully drained
 */

class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();

    // Ring buffer: ~10 seconds at 24 kHz
    this._ringBufferSize = 24000 * 10;
    this._ringBuffer = new Float32Array(this._ringBufferSize);
    this._writeIndex = 0;
    this._readIndex = 0;
    this._samplesAvailable = 0;
    this._playing = false;
    this._draining = false; // true when no more data will arrive

    this.port.onmessage = (event) => {
      const { command, data } = event.data;

      if (command === "play") {
        this._enqueue(data);
        this._playing = true;
        this._draining = false;
      } else if (command === "stop") {
        this._playing = false;
        this._draining = false;
        this._writeIndex = 0;
        this._readIndex = 0;
        this._samplesAvailable = 0;
      } else if (command === "drain") {
        // Signal that no more chunks are coming — play until empty
        this._draining = true;
      }
    };
  }

  /**
   * Convert Int16 PCM to Float32 and write into ring buffer.
   */
  _enqueue(arrayBuffer) {
    const int16 = new Int16Array(arrayBuffer);
    const sampleCount = int16.length;

    for (let i = 0; i < sampleCount; i++) {
      if (this._samplesAvailable >= this._ringBufferSize) {
        // Buffer full — drop oldest samples (shouldn't happen normally)
        this._readIndex = (this._readIndex + 1) % this._ringBufferSize;
        this._samplesAvailable--;
      }

      // Int16 → Float32
      this._ringBuffer[this._writeIndex] = int16[i] / 32768.0;
      this._writeIndex = (this._writeIndex + 1) % this._ringBufferSize;
      this._samplesAvailable++;
    }
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    if (!output || !output[0]) {
      return true;
    }

    const channel = output[0];

    if (!this._playing) {
      // Output silence
      channel.fill(0);
      return true;
    }

    for (let i = 0; i < channel.length; i++) {
      if (this._samplesAvailable > 0) {
        channel[i] = this._ringBuffer[this._readIndex];
        this._readIndex = (this._readIndex + 1) % this._ringBufferSize;
        this._samplesAvailable--;
      } else {
        channel[i] = 0; // Silence when buffer is empty
      }
    }

    // Notify main thread when draining and buffer is empty
    if (this._draining && this._samplesAvailable === 0) {
      this._playing = false;
      this._draining = false;
      this.port.postMessage({ type: "playback_complete" });
    }

    return true; // Keep processor alive
  }
}

registerProcessor("pcm-player-processor", PCMPlayerProcessor);
