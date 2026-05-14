/**
 * AudioWorklet processor for capturing microphone PCM and downsampling to 16 kHz Int16 mono.
 *
 * Commands received via port:
 *   { command: "start" } — begin capturing and emitting chunks
 *   { command: "stop" }  — flush remaining samples and stop
 *
 * Messages emitted via port:
 *   { type: "audio", data: ArrayBuffer }  — Int16 PCM at 16 kHz
 */
class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._active = false;
    this._buffer = [];          // Accumulated Float32 samples
    this._chunkSize = 4800;     // 300 ms at 16 kHz

    this.port.onmessage = (event) => {
      const { command } = event.data;
      if (command === "start") {
        this._active = true;
        this._buffer = [];
      } else if (command === "stop") {
        this._active = false;
        this._flush();
      }
    };
  }

  process(inputs) {
    if (!this._active) return true;

    const input = inputs[0];
    const channel = input && input[0];
    if (!channel) return true;

    // Accumulate samples
    for (let i = 0; i < channel.length; i++) {
      this._buffer.push(channel[i]);
    }

    // Emit full chunks
    while (this._buffer.length >= this._chunkSize) {
      const chunk = this._buffer.splice(0, this._chunkSize);
      this._emit(chunk);
    }

    return true;
  }

  _flush() {
    if (this._buffer.length > 0) {
      this._emit(this._buffer);
      this._buffer = [];
    }
  }

  _emit(float32Samples) {
    const int16 = new Int16Array(float32Samples.length);
    for (let i = 0; i < float32Samples.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Samples[i]));
      int16[i] = s < 0 ? s * 32768 : s * 32767;
    }
    this.port.postMessage({ type: "audio", data: int16.buffer }, [int16.buffer]);
  }
}

registerProcessor("pcm-recorder-processor", PcmRecorderProcessor);
