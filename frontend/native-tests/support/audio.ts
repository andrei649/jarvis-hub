import { vi } from 'vitest';

let recording = false;
export function setNativeRecording(value: boolean) { recording = value; }
let permission: Promise<{ granted: boolean }> = Promise.resolve({ granted: true });
export function setPermissionResponse(value: Promise<{ granted: boolean }>) { permission = value; }
export const audioRecorder = {
  requestPermission: vi.fn(async () => permission),
  prepare: vi.fn(async () => {}),
  record: vi.fn((_options: { forDuration: number }) => { recording = true; }),
  stop: vi.fn(async () => { recording = false; }),
  getStatus: vi.fn(() => ({ isRecording: recording, metering: -20, url: 'file:///fixture/clip.m4a' })),
  release: vi.fn(() => {}),
  get uri() { return 'file:///fixture/clip.m4a'; },
};
export function resetAudio() {
  recording = false;
  permission = Promise.resolve({ granted: true });
  audioRecorder.requestPermission.mockClear();
  audioRecorder.prepare.mockClear(); audioRecorder.record.mockClear();
  audioRecorder.stop.mockClear(); audioRecorder.getStatus.mockClear();
  audioRecorder.release.mockClear();
}
export const RecordingPresets = { HIGH_QUALITY: {
  extension: '.m4a', sampleRate: 44100, numberOfChannels: 2, bitRate: 128000,
  ios: { outputFormat: 'aac' }, android: { outputFormat: 'mpeg4', audioEncoder: 'aac' },
} };
export const requestRecordingPermissionsAsync = () => audioRecorder.requestPermission();
export const getRecordingPermissionsAsync = async () => ({ granted: true });
export const AudioModule = { AudioRecorder: class {
  constructor(_options: unknown) {}
  prepareToRecordAsync() { return audioRecorder.prepare(); }
  record(options: { forDuration: number }) { audioRecorder.record(options); }
  stop() { return audioRecorder.stop(); }
  getStatus() { return audioRecorder.getStatus(); }
  get uri() { return audioRecorder.uri; }
  release() { audioRecorder.release(); }
} };
export const createAudioPlayer=()=>({play(){},remove(){},addListener(){return {remove(){}};}});
export const setAudioModeAsync=async()=>{};
