import glob
import subprocess

import imageio_ffmpeg

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
webm = glob.glob(r"C:\Users\Administrator\Desktop\text2cad\video_out\*.webm")[0]
mp4 = r"C:\Users\Administrator\Desktop\text2cad\造物工坊-演示视频.mp4"
subprocess.run([
    ffmpeg, "-y", "-i", webm,
    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    mp4,
])
print("转换完成:", mp4)
