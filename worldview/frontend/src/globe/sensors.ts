import { PostProcessStage, type Scene } from "cesium";
import type { SensorMode } from "@/lib/store/timelineStore";

// Sensor grades (the God's Eye View sensor stack, on Cesium's post-process pipeline).
//
// These are VISUAL grades applied to the rendered frame — a thermal-looking picture is not
// thermal data, and the HUD labels them as grades for exactly that reason. "normal" adds no
// stage at all, so the default path pays nothing.

const THERMAL = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;
void main() {
  vec3 c = texture(colorTexture, v_textureCoordinates).rgb;
  float t = clamp(dot(c, vec3(0.299, 0.587, 0.114)), 0.0, 1.0);
  // Iron ramp: black → indigo → magenta → orange → white.
  vec3 cold = mix(vec3(0.02, 0.02, 0.10), vec3(0.35, 0.05, 0.55), smoothstep(0.0, 0.35, t));
  vec3 warm = mix(cold, vec3(1.0, 0.35, 0.05), smoothstep(0.35, 0.72, t));
  vec3 hot = mix(warm, vec3(1.0, 0.98, 0.85), smoothstep(0.72, 1.0, t));
  out_FragColor = vec4(hot, 1.0);
}
`;

const NIGHT = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;
void main() {
  vec2 uv = v_textureCoordinates;
  vec3 c = texture(colorTexture, uv).rgb;
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  // Image-intensifier response: gain the signal, crush it into the phosphor green.
  float gained = clamp(pow(l * 1.85, 0.75), 0.0, 1.0);
  vec3 phosphor = vec3(0.10, 1.0, 0.35) * gained;
  // Static grain, deterministic per pixel (no time uniform — stillness is the default).
  float grain = fract(sin(dot(uv, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
  phosphor += grain * 0.045;
  // Tube vignette.
  float r = distance(uv, vec2(0.5));
  phosphor *= smoothstep(0.85, 0.35, r);
  out_FragColor = vec4(phosphor, 1.0);
}
`;

const TACTICAL = `
uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;
void main() {
  vec2 uv = v_textureCoordinates;
  vec3 c = texture(colorTexture, uv).rgb;
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  // Posterize the terrain into a few contour bands, then tint to the HUD's signal blue.
  float bands = floor(l * 6.0) / 6.0;
  vec3 tinted = mix(vec3(0.015, 0.03, 0.055), vec3(0.17, 0.72, 0.94), bands);
  // Fine scanlines, aligned to the pixel grid rather than to time.
  float scan = 0.94 + 0.06 * step(0.5, fract(uv.y * 380.0));
  out_FragColor = vec4(tinted * scan, 1.0);
}
`;

const SHADERS: Partial<Record<SensorMode, string>> = {
  thermal: THERMAL,
  night: NIGHT,
  tactical: TACTICAL,
};

/** Human labels for the sensor selector (kept next to the shaders they name). */
export const SENSOR_LABELS: Record<SensorMode, string> = {
  normal: "NORMAL",
  thermal: "THERMAL",
  night: "NIGHT",
  tactical: "TACTICAL",
};

/**
 * Swaps the scene's sensor grade. Holds the single active stage so repeated calls never stack
 * post-process passes; "normal" removes the stage entirely.
 */
export function createSensorController(scene: Scene) {
  let active: PostProcessStage | null = null;
  let activeMode: SensorMode = "normal";

  function clear() {
    if (active) {
      scene.postProcessStages.remove(active);
      active = null;
    }
  }

  return {
    get mode(): SensorMode {
      return activeMode;
    },
    apply(mode: SensorMode) {
      if (mode === activeMode) return;
      clear();
      activeMode = mode;
      const fragmentShader = SHADERS[mode];
      if (!fragmentShader) return;
      active = scene.postProcessStages.add(
        new PostProcessStage({ name: `wv-sensor-${mode}`, fragmentShader }),
      ) as PostProcessStage;
    },
    destroy() {
      clear();
      activeMode = "normal";
    },
  };
}
