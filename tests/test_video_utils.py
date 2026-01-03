from pathlib import Path
import cv2
import numpy as np
import pytest
import video_utils
import main


def create_dummy_video(path, duration_sec=2, fps=10, width=640, height=480):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(path, fourcc, fps, (width, height))
    total_frames = int(duration_sec * fps)
    for _ in range(total_frames):
        frame = (255 * np.random.rand(height, width, 3)).astype(np.uint8)
        out.write(frame)
    out.release()


def test_load_video(tmp_path):
    video_file = tmp_path / "test_video.mp4"
    create_dummy_video(video_file, duration_sec=3, fps=10)

    cap, total_frames, fps = video_utils.load_video(str(video_file))
    assert total_frames == 30
    assert fps == 10.0
    cap.release()

    if video_utils.has_ffmpeg_support():
        cap_ffmpeg, total_frames_ffmpeg, fps_ffmpeg = video_utils.load_video(
            str(video_file), backend="ffmpeg"
        )
        assert total_frames_ffmpeg == 30
        assert fps_ffmpeg == 10.0
        cap_ffmpeg.release()


def test_split_video(tmp_path):
    video_file = tmp_path / "test_video.mp4"
    fps = 10
    create_dummy_video(video_file, duration_sec=5, fps=fps)

    segments = [
        main.Segment(
            segment_id=1,
            fps=fps,
            start_frame=0,
            end_frame=20,
            title="part1",
            layer=1,
        ),
        main.Segment(
            segment_id=2,
            fps=fps,
            start_frame=20,
            end_frame=50,
            title="part2",
            layer=2,
        ),
    ]
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    video_utils.split_video(str(video_file), segments, str(output_dir))

    output_files = list(output_dir.glob("*.mp4"))
    assert len(output_files) == 2
    expected_filenames = {
        f"test_video_l1-part1.mp4",
        f"test_video_l2-part2.mp4",
    }
    actual_filenames = {f.name for f in output_files}
    assert actual_filenames == expected_filenames
