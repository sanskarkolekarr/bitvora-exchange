import { Renderer, Program, Mesh, Triangle } from 'https://unpkg.com/ogl';

const vertexShader = `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0, 1);
}
`;

const fragmentShader = `
precision highp float;

uniform float uTime;
uniform vec3 uResolution;
uniform float uSpeed;
uniform float uScale;
uniform float uBrightness;
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform float uNoiseFreq;
uniform float uNoiseAmp;
uniform float uBandHeight;
uniform float uBandSpread;
uniform float uOctaveDecay;
uniform float uLayerOffset;
uniform float uColorSpeed;
uniform vec2 uMouse;
uniform float uMouseInfluence;
uniform bool uEnableMouse;

#define TAU 6.28318

vec3 gradientHash(vec3 p) {
  p = vec3(
    dot(p, vec3(127.1, 311.7, 234.6)),
    dot(p, vec3(269.5, 183.3, 198.3)),
    dot(p, vec3(169.5, 283.3, 156.9))
  );
  vec3 h = fract(sin(p) * 43758.5453123);
  float phi = acos(2.0 * h.x - 1.0);
  float theta = TAU * h.y;
  return vec3(cos(theta) * sin(phi), sin(theta) * cos(phi), cos(phi));
}

float quinticSmooth(float t) {
  float t2 = t * t;
  float t3 = t * t2;
  return 6.0 * t3 * t2 - 15.0 * t2 * t2 + 10.0 * t3;
}

vec3 cosineGradient(float t, vec3 a, vec3 b, vec3 c, vec3 d) {
  return a + b * cos(TAU * (c * t + d));
}

float perlin3D(float amplitude, float frequency, float px, float py, float pz) {
  float x = px * frequency;
  float y = py * frequency;

  float fx = floor(x); float fy = floor(y); float fz = floor(pz);
  float cx = ceil(x);  float cy = ceil(y);  float cz = ceil(pz);

  vec3 g000 = gradientHash(vec3(fx, fy, fz));
  vec3 g100 = gradientHash(vec3(cx, fy, fz));
  vec3 g010 = gradientHash(vec3(fx, cy, fz));
  vec3 g110 = gradientHash(vec3(cx, cy, fz));
  vec3 g001 = gradientHash(vec3(fx, fy, cz));
  vec3 g101 = gradientHash(vec3(cx, fy, cz));
  vec3 g011 = gradientHash(vec3(fx, cy, cz));
  vec3 g111 = gradientHash(vec3(cx, cy, cz));

  float d000 = dot(g000, vec3(x - fx, y - fy, pz - fz));
  float d100 = dot(g100, vec3(x - cx, y - fy, pz - fz));
  float d010 = dot(g010, vec3(x - fx, y - cy, pz - fz));
  float d110 = dot(g110, vec3(x - cx, y - cy, pz - fz));
  float d001 = dot(g001, vec3(x - fx, y - fy, pz - cz));
  float d101 = dot(g101, vec3(x - cx, y - fy, pz - cz));
  float d011 = dot(g011, vec3(x - fx, y - cy, pz - cz));
  float d111 = dot(g111, vec3(x - cx, y - cy, pz - cz));

  float sx = quinticSmooth(x - fx);
  float sy = quinticSmooth(y - fy);
  float sz = quinticSmooth(pz - fz);

  float lx00 = mix(d000, d100, sx);
  float lx10 = mix(d010, d110, sx);
  float lx01 = mix(d001, d101, sx);
  float lx11 = mix(d011, d111, sx);

  float ly0 = mix(lx00, lx10, sy);
  float ly1 = mix(lx01, lx11, sy);

  return amplitude * mix(ly0, ly1, sz);
}

float auroraGlow(float t, vec2 shift) {
  vec2 uv = gl_FragCoord.xy / uResolution.y;
  uv += shift;

  float noiseVal = 0.0;
  float freq = uNoiseFreq;
  float amp = uNoiseAmp;
  vec2 samplePos = uv * uScale;

  for (float i = 0.0; i < 3.0; i += 1.0) {
    noiseVal += perlin3D(amp, freq, samplePos.x, samplePos.y, t);
    amp *= uOctaveDecay;
    freq *= 2.0;
  }

  float yBand = uv.y * 10.0 - uBandHeight * 10.0;
  return 0.3 * max(exp(uBandSpread * (1.0 - 1.1 * abs(noiseVal + yBand))), 0.0);
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.xy;
  float t = uSpeed * 0.4 * uTime;

  vec2 shift = vec2(0.0);
  if (uEnableMouse) {
    shift = (uMouse - 0.5) * uMouseInfluence;
  }

  vec3 col = vec3(0.0);
  col += 0.99 * auroraGlow(t, shift) * cosineGradient(uv.x + uTime * uSpeed * 0.2 * uColorSpeed, vec3(0.5), vec3(0.5), vec3(1.0), vec3(0.3, 0.20, 0.20)) * uColor1;
  col += 0.99 * auroraGlow(t + uLayerOffset, shift) * cosineGradient(uv.x + uTime * uSpeed * 0.1 * uColorSpeed, vec3(0.5), vec3(0.5), vec3(2.0, 1.0, 0.0), vec3(0.5, 0.20, 0.25)) * uColor2;

  col *= uBrightness;
  float alpha = clamp(length(col), 0.0, 1.0);
  gl_FragColor = vec4(col, alpha);
}
`;

function hexToVec3(hex) {
    const h = hex.replace('#', '');
    return [
      parseInt(h.slice(0, 2), 16) / 255,
      parseInt(h.slice(2, 4), 16) / 255,
      parseInt(h.slice(4, 6), 16) / 255
    ];
}

class SoftAurora {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            speed: 0.6,
            scale: 1.5,
            brightness: 1.2,
            color1: '#4f46e5', // Indigo
            color2: '#9333ea', // Purple
            noiseFrequency: 2.5,
            noiseAmplitude: 1.0,
            bandHeight: 0.5,
            bandSpread: 1.2,
            octaveDecay: 0.1,
            layerOffset: 0,
            colorSpeed: 1.0,
            enableMouseInteraction: true,
            mouseInfluence: 0.25,
            ...options
        };

        this.renderer = new Renderer({ alpha: true, premultipliedAlpha: false });
        this.gl = this.renderer.gl;
        this.gl.clearColor(0, 0, 0, 0);

        this.currentMouse = [0.5, 0.5];
        this.targetMouse = [0.5, 0.5];

        this.handleMouseMove = this.handleMouseMove.bind(this);
        this.handleMouseLeave = this.handleMouseLeave.bind(this);
        this.resize = this.resize.bind(this);

        window.addEventListener('resize', this.resize);
        this.resize();

        const geometry = new Triangle(this.gl);
        this.program = new Program(this.gl, {
            vertex: vertexShader,
            fragment: fragmentShader,
            uniforms: {
                uTime: { value: 0 },
                uResolution: { value: [this.gl.canvas.width, this.gl.canvas.height, this.gl.canvas.width / this.gl.canvas.height] },
                uSpeed: { value: this.options.speed },
                uScale: { value: this.options.scale },
                uBrightness: { value: this.options.brightness },
                uColor1: { value: hexToVec3(this.options.color1) },
                uColor2: { value: hexToVec3(this.options.color2) },
                uNoiseFreq: { value: this.options.noiseFrequency },
                uNoiseAmp: { value: this.options.noiseAmplitude },
                uBandHeight: { value: this.options.bandHeight },
                uBandSpread: { value: this.options.bandSpread },
                uOctaveDecay: { value: this.options.octaveDecay },
                uLayerOffset: { value: this.options.layerOffset },
                uColorSpeed: { value: this.options.colorSpeed },
                uMouse: { value: new Float32Array([0.5, 0.5]) },
                uMouseInfluence: { value: this.options.mouseInfluence },
                uEnableMouse: { value: this.options.enableMouseInteraction }
            }
        });

        this.mesh = new Mesh(this.gl, { geometry: geometry, program: this.program });
        // Use insertBefore to put canvas at the bottom layer of the container
        this.container.insertBefore(this.gl.canvas, this.container.firstChild);
        this.gl.canvas.style.position = 'absolute';
        this.gl.canvas.style.inset = '0';
        this.gl.canvas.style.width = '100%';
        this.gl.canvas.style.height = '100%';

        if (this.options.enableMouseInteraction) {
            window.addEventListener('mousemove', this.handleMouseMove);
            window.addEventListener('mouseleave', this.handleMouseLeave);
        }

        this.animationFrameId = null;
        this.update = this.update.bind(this);
        this.update(0);
    }

    handleMouseMove(e) {
        const rect = this.gl.canvas.getBoundingClientRect();
        this.targetMouse = [
            (e.clientX - rect.left) / rect.width,
            1.0 - (e.clientY - rect.top) / rect.height
        ];
    }

    handleMouseLeave() {
        this.targetMouse = [0.5, 0.5];
    }

    resize() {
        this.renderer.setSize(this.container.offsetWidth, this.container.offsetHeight);
        if (this.program) {
            this.program.uniforms.uResolution.value = [this.gl.canvas.width, this.gl.canvas.height, this.gl.canvas.width / this.gl.canvas.height];
        }
    }

    update(time) {
        this.animationFrameId = requestAnimationFrame(this.update);
        this.program.uniforms.uTime.value = time * 0.001;

        if (this.options.enableMouseInteraction) {
            this.currentMouse[0] += 0.05 * (this.targetMouse[0] - this.currentMouse[0]);
            this.currentMouse[1] += 0.05 * (this.targetMouse[1] - this.currentMouse[1]);
            this.program.uniforms.uMouse.value[0] = this.currentMouse[0];
            this.program.uniforms.uMouse.value[1] = this.currentMouse[1];
        } else {
            this.program.uniforms.uMouse.value[0] = 0.5;
            this.program.uniforms.uMouse.value[1] = 0.5;
        }

        this.renderer.render({ scene: this.mesh });
    }

    destroy() {
        cancelAnimationFrame(this.animationFrameId);
        window.removeEventListener('resize', this.resize);
        if (this.options.enableMouseInteraction) {
            window.removeEventListener('mousemove', this.handleMouseMove);
            window.removeEventListener('mouseleave', this.handleMouseLeave);
        }
        this.container.removeChild(this.gl.canvas);
        const ext = this.gl.getExtension('WEBGL_lose_context');
        if (ext) ext.loseContext();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const auroraContainer = document.getElementById('aurora-bg');
    if (auroraContainer) {
        new SoftAurora(auroraContainer, {
            color1: '#2b1a59', // Deep Purple
            color2: '#0e1b42', // Deep Blue
            bandSpread: 1.5,
            brightness: 1.2
        });
    }
});
