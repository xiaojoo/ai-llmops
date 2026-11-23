package com.webapp.plugin.util;

import com.intellij.openapi.diagnostic.Logger;

import javax.sound.sampled.AudioFormat;
import javax.sound.sampled.AudioSystem;
import javax.sound.sampled.DataLine;
import javax.sound.sampled.LineUnavailableException;
import javax.sound.sampled.TargetDataLine;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * 麦克风录音器（JDK javax.sound.sampled）。
 * <p>JCEF 不支持 getUserMedia/MediaRecorder（语音转文字在插件里一直无法启动），
 * 改由本类在 IDE 进程内采集系统默认输入设备：start() 开始录音（16kHz/16bit/单声道 PCM），
 * stopAndGetWav() 停止并返回 WAV 字节。录到的音频走现有上传通道（MinIO）后由后端识别。
 */
public final class VoiceRecorder {

    private static final Logger LOG = Logger.getInstance(VoiceRecorder.class);

    private static final float SAMPLE_RATE = 16000f;
    private static final int SAMPLE_BITS = 16;
    private static final int CHANNELS = 1;

    private TargetDataLine line;
    private ByteArrayOutputStream out;
    private Thread captureThread;
    private volatile boolean running;

    /** 开始录音；已在录音时 no-op。无输入设备/被占用抛 LineUnavailableException。 */
    public synchronized void start() throws LineUnavailableException {
        if (running) return;
        AudioFormat format = new AudioFormat(SAMPLE_RATE, SAMPLE_BITS, CHANNELS, true, false);
        DataLine.Info info = new DataLine.Info(TargetDataLine.class, format);
        line = (TargetDataLine) AudioSystem.getLine(info);
        line.open(format);
        logCaptureDevices(); // 诊断：记录可用输入设备与所用设备
        out = new ByteArrayOutputStream();
        running = true;
        captureThread = new Thread(() -> {
            byte[] buf = new byte[4096];
            while (running) {
                int n = line.read(buf, 0, buf.length);
                if (n > 0) out.write(buf, 0, n);
            }
        }, "webapp-voice-capture");
        captureThread.start();
        line.start();
        LOG.info("WebApp voice recording started");
    }

    /** 诊断日志：列出系统可用录音设备与当前打开的线（麦克风采到静音时排查用）。 */
    private static void logCaptureDevices() {
        try {
            javax.sound.sampled.Mixer.Info[] mixers = AudioSystem.getMixerInfo();
            StringBuilder sb = new StringBuilder("capture devices:");
            for (javax.sound.sampled.Mixer.Info mi : mixers) {
                try {
                    javax.sound.sampled.Mixer m = AudioSystem.getMixer(mi);
                    boolean hasCapture = m.isLineSupported(new DataLine.Info(TargetDataLine.class,
                        new AudioFormat(SAMPLE_RATE, SAMPLE_BITS, CHANNELS, true, false)));
                    if (hasCapture) {
                        sb.append("\n  - ").append(mi.getName()).append(" (").append(mi.getVendor()).append(")");
                    }
                } catch (Exception ignored) {
                }
            }
            LOG.info(sb.toString());
        } catch (Exception e) {
            LOG.warn("WebApp enumerate capture devices failed", e);
        }
    }

    /** 停止录音并返回 WAV 字节；未在录音或没采到声音返回 null。 */
    public synchronized byte[] stopAndGetWav() {
        if (!running || line == null) return null;
        running = false;
        try {
            line.stop();
            line.close();
        } catch (Exception ignored) {
        }
        if (captureThread != null) {
            try {
                captureThread.join(2000);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            captureThread = null;
        }
        byte[] pcm = out == null ? new byte[0] : out.toByteArray();
        if (pcm.length == 0) return null;
        return buildWav(pcm, SAMPLE_RATE, SAMPLE_BITS, CHANNELS);
    }

    public synchronized boolean isRecording() {
        return running;
    }

    /** 纯逻辑：PCM 字节拼 44 字节 WAV 头（RIFF/PCM/fmt/data），可单测。 */
    public static byte[] buildWav(byte[] pcm, float sampleRate, int sampleBits, int channels) {
        int dataSize = pcm.length;
        int blockAlign = channels * sampleBits / 8;
        int byteRate = Math.round(sampleRate) * blockAlign;
        ByteArrayOutputStream wav = new ByteArrayOutputStream(dataSize + 44);
        try {
            wav.write("RIFF".getBytes(StandardCharsets.US_ASCII));
            writeIntLE(wav, 36 + dataSize);
            wav.write("WAVE".getBytes(StandardCharsets.US_ASCII));
            wav.write("fmt ".getBytes(StandardCharsets.US_ASCII));
            writeIntLE(wav, 16);                       // fmt chunk 大小
            writeShortLE(wav, 1);                      // PCM 编码
            writeShortLE(wav, channels);
            writeIntLE(wav, Math.round(sampleRate));
            writeIntLE(wav, byteRate);
            writeShortLE(wav, blockAlign);
            writeShortLE(wav, sampleBits);
            wav.write("data".getBytes(StandardCharsets.US_ASCII));
            writeIntLE(wav, dataSize);
            wav.write(pcm);
        } catch (IOException e) {
            throw new IllegalStateException("wav 构造失败", e); // ByteArrayOutputStream 不会真实发生
        }
        return wav.toByteArray();
    }

    private static void writeIntLE(ByteArrayOutputStream out, int v) {
        out.write(v & 0xff);
        out.write((v >> 8) & 0xff);
        out.write((v >> 16) & 0xff);
        out.write((v >> 24) & 0xff);
    }

    private static void writeShortLE(ByteArrayOutputStream out, int v) {
        out.write(v & 0xff);
        out.write((v >> 8) & 0xff);
    }
}
