import pytest

import main


class TestSegment:
    """Test Segment class"""

    def test_segment_initialization(self):
        """Test Segment initialization"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=100,
        )
        assert segment.fps == 30
        assert segment.segment_id == 1
        assert segment.layer == 1
        assert segment.title == "Test"
        assert segment.start_frame == 0
        assert segment.end_frame == 100

    def test_segment_duration(self):
        """Test duration calculation"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=300,
        )
        assert segment.duration == 300  # end_frame - start_frame = 300 frames

    def test_segment_start_time(self):
        """Test start_time property"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=30,
            end_frame=60,
        )
        assert segment.start_time == 1.0  # 30 frames / 30 fps = 1 second

    def test_segment_end_time(self):
        """Test end_time property"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=60,
        )
        assert segment.end_time == 2.0  # 60 frames / 30 fps = 2 seconds

    def test_segment_start_time_setter(self):
        """Test start_time setter"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=100,
        )
        segment.start_time = 2.0
        assert segment.start_frame == 60

    def test_segment_end_time_setter(self):
        """Test end_time setter"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=100,
        )
        segment.end_time = 3.0
        assert segment.end_frame == 90

    def test_segment_to_dict(self):
        """Test to_dict conversion"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=300,
        )
        data = segment.to_dict()
        assert data["id"] == 1
        assert data["layer"] == 1
        assert data["title"] == "Test"
        assert data["start"] == 0.0
        assert data["end"] == 10.0

    def test_segment_ui_property(self):
        """Test UI property getter/setter"""
        segment = main.Segment(
            fps=30,
            segment_id=1,
            layer=1,
            title="Test",
            start_frame=0,
            end_frame=100,
        )
        ui_data = {"widget": "test"}
        segment.ui = ui_data
        assert segment.ui == ui_data


class TestSegmentManager:
    """Test SegmentManager class"""

    def test_segment_manager_initialization(self):
        """Test SegmentManager initialization"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        assert manager.fps == 30
        assert manager.total_frames == 3000
        assert len(manager) == 0

    def test_segment_manager_append(self):
        """Test appending segment"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        assert len(manager) == 1
        assert manager.items[0].title == "Seg1"

    def test_segment_manager_get_max_list_index(self):
        """Test get_max_list_index"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg2")
        assert manager.get_max_list_index() == 2

    def test_segment_manager_get_max_list_index_empty(self):
        """Test get_max_list_index with empty list"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        assert manager.get_max_list_index() == 0

    def test_segment_manager_get_segment_by_id(self):
        """Test get_segment_by_id"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        segment = manager.get_segment_by_id(1)
        assert segment is not None
        assert segment.title == "Seg1"

    def test_segment_manager_get_segment_by_id_not_found(self):
        """Test get_segment_by_id when not found"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        segment = manager.get_segment_by_id(999)
        assert segment is None

    def test_segment_manager_get_segment_by_time(self):
        """Test get_segment_by_time"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        segment = manager.get_segment_by_time(5.0, layer=1)
        assert segment is not None
        assert segment.title == "Seg1"

    def test_segment_manager_get_segment_by_time_not_found(self):
        """Test get_segment_by_time when not found"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        segment = manager.get_segment_by_time(50.0, layer=1)
        assert segment is None

    def test_segment_manager_filter_by_layers(self):
        """Test filter_by_layers"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=2, start_frame=0, end_frame=300, title="Seg2")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg3")

        filtered = manager.filter_by_layers([1])
        assert len(filtered) == 2
        assert all(s.layer == 1 for s in filtered)

    def test_segment_manager_clear(self):
        """Test clear method"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=2, start_frame=0, end_frame=300, title="Seg2")

        manager.clear()
        assert len(manager) == 0

    def test_segment_manager_clear_by_layer(self):
        """Test clear method with specific layer"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=2, start_frame=0, end_frame=300, title="Seg2")

        manager.clear(layers=[1])
        assert len(manager) == 1
        assert manager.items[0].layer == 2

    def test_segment_manager_remove_segment_by_id(self):
        """Test remove_segment_by_id"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg2")

        manager.remove_segment_by_id(1)
        assert len(manager) == 1
        assert manager.items[0].segment_id == 2

    def test_segment_manager_reset_list_indexes(self):
        """Test reset_list_indexes"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg2")

        manager.remove_segment_by_id(1)
        manager.reset_list_indexes()

        assert manager.items[0].segment_id == 1

    def test_segment_manager_get_segments_before_time(self):
        """Test get_segments_before_time"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(
            layer=1, start_frame=0, end_frame=300, title="Seg1"
        )  # 0-10s
        manager.append(
            layer=1, start_frame=300, end_frame=600, title="Seg2"
        )  # 10-20s
        manager.append(
            layer=1, start_frame=600, end_frame=900, title="Seg3"
        )  # 20-30s

        # end_time <= 15.0s condition
        before = manager.get_segments_before_time(15.0, layer=1)
        assert len(before) == 1  # Only Seg1 (end_time=10.0)

    def test_segment_manager_get_segments_after_time(self):
        """Test get_segments_after_time"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg2")
        manager.append(layer=1, start_frame=600, end_frame=900, title="Seg3")

        after = manager.get_segments_after_time(15.0, layer=1)
        assert len(after) == 1

    def test_segment_manager_iteration(self):
        """Test iteration over manager"""
        manager = main.SegmentManager(fps=30, total_frames=3000)
        manager.append(layer=1, start_frame=0, end_frame=300, title="Seg1")
        manager.append(layer=1, start_frame=300, end_frame=600, title="Seg2")

        segments = list(manager)
        assert len(segments) == 2
