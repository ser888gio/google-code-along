/**
 * AudioWorklet processor for playing back PCM audio (24 kHz, Int16 mono).
 *
 * Commands received via port:
 *   { command: "play", data: ArrayBuffer }  — enqueue a chunk of Int16 PCM
 *   { command: "drain" }                    — signal end of stream; post "playback_complete" when buffer empties
 *   { command: "stop" }                     — immediately clear the buffer and stop
 */
class PcmPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._queue = [];        // Float32Array chunks waiting to be played
    this._offset = 0;        // Read position within the front chunk
    this._draining = false;  // true once "drain" is received

    this.port.onmessage = (event) => {
      const { command, data } = event.data;

      if (command === "play") {
        // Convert Int16 PCM → Float32 in [-1, 1]
        const int16 = new Int16Array(data);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
          float32[i] = int16[i] / 32768;
        }
        this._queue.push(float32);
        this._draining = false;
      } else if (command === "drain") {
        this._draining = true;
      } else if (command === "stop") {
        this._queue = [];
        this._draining = false;
      }
    };
  }

  process(_inputs, outputs) {
    const output = outputs[0];
    const channel = output[0];
    if (!channel) return true;

    let written = 0;

    while (written < channel.length && this._queue.length > 0) {
      const chunk = this._queue[0];
      const remaining = chunk.length - this._offset;
      const toCopy = Math.min(remaining, channel.length - written);

      channel.set(chunk.subarray(this._offset, this._offset + toCopy), written);
      written += toCopy;
      this._offset += toCopy;

      if (this._offset >= chunk.length) {
        this._queue.shift();
        this._offset = 0;
      }
    }

    // Fill silence if we ran out of data
    for (let i = written; i < channel.length; i++) {
      channel[i] = 0;
    }

    // Notify when drain is complete
    if (this._draining && this._queue.length === 0) {
      this.port.postMessage({ type: "playback_complete" });
      this._draining = false;
    }

    return true;
  }
}

registerProcessor("pcm-player-processor", PcmPlayerProcessor);
