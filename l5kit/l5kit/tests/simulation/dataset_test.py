
from pathlib import Path

import numpy as np
import pytest

from l5kit.data import AGENT_DTYPE, ChunkedDataset, FRAME_DTYPE, LocalDataManager, SCENE_DTYPE, TL_FACE_DTYPE
from l5kit.dataset import EgoDataset
from l5kit.geometry import rotation33_as_yaw
from l5kit.rasterization import build_rasterizer
from l5kit.simulation.dataset import SimulationDataset


def test_simulation_ego(zarr_cat_dataset: ChunkedDataset, dmg: LocalDataManager, cfg: dict, tmp_path: Path) -> None:
    rasterizer = build_rasterizer(cfg, dmg)

    scene_indices = list(range(len(zarr_cat_dataset.scenes)))

    ego_dataset = EgoDataset(cfg, zarr_cat_dataset, rasterizer)
    dataset = SimulationDataset(ego_dataset, scene_indices)

    # this also ensure order is checked
    assert list(dataset.scene_dataset_batch.keys()) == scene_indices

    # ensure we can call the getitem
    out_0 = dataset[(0, 0)]
    assert len(out_0) > 0
    out_last = dataset[(0, len(dataset) - 1)]
    assert len(out_last) > 0
    with pytest.raises(IndexError):
        _ = dataset[(0, len(dataset))]

    # ensure we can call the aggregated get frame
    out_0 = dataset.rasterise_frame_batch(0)
    assert len(out_0) == len(scene_indices)
    out_last = dataset.rasterise_frame_batch(len(dataset) - 1)
    assert len(out_last) == len(scene_indices)
    with pytest.raises(IndexError):
        _ = dataset.rasterise_frame_batch(len(dataset))

    # ensure we can set the ego in multiple frames for all scenes
    frame_indices = np.random.randint(0, len(dataset), 10)
    for frame_idx in frame_indices:
        mock_tr = np.random.rand(len(scene_indices), 12, 2)
        mock_yaw = np.random.rand(len(scene_indices), 12)

        dataset.set_ego(frame_idx, 0, mock_tr, mock_yaw)

        for scene_idx in scene_indices:
            scene_zarr = dataset.scene_dataset_batch[scene_idx].dataset
            ego_tr = scene_zarr.frames["ego_translation"][frame_idx]
            ego_yaw = rotation33_as_yaw(scene_zarr.frames["ego_rotation"][frame_idx])

            assert np.allclose(mock_tr[scene_idx, 0], ego_tr[:2])
            assert np.allclose(mock_yaw[scene_idx, 0], ego_yaw)


def test_simulation_agents(zarr_cat_dataset: ChunkedDataset, dmg: LocalDataManager, cfg: dict, tmp_path: Path) -> None:
    rasterizer = build_rasterizer(cfg, dmg)

    scene_indices = list(range(len(zarr_cat_dataset.scenes)))

    ego_dataset = EgoDataset(cfg, zarr_cat_dataset, rasterizer)
    dataset = SimulationDataset(ego_dataset, scene_indices, distance_th_close=30)

    # nothing should be tracked
    assert len(dataset.agents_tracked) == 0

    agents_dict = dataset.rasterise_agents_frame_batch(0)

    # we should have the same agents in each scene
    for k in agents_dict:
        assert (0, k[1]) in agents_dict

    # now everything should be tracked
    assert len(dataset.agents_tracked) == len(agents_dict)


def test_simulation_agents_mock(dmg: LocalDataManager, cfg: dict, tmp_path: Path) -> None:
    zarr_dataset = _mock_dataset()
    rasterizer = build_rasterizer(cfg, dmg)

    ego_dataset = EgoDataset(cfg, zarr_dataset, rasterizer)
    dataset = SimulationDataset(ego_dataset, [0], distance_th_close=10)

    # nothing should be tracked
    assert len(dataset.agents_tracked) == 0

    agents_dict = dataset.rasterise_agents_frame_batch(0)

    # only (0, 1) should be in
    assert len(agents_dict) == 1 and (0, 1) in agents_dict
    assert len(dataset.agents_tracked) == 1

    agents_dict = dataset.rasterise_agents_frame_batch(1)
    assert len(agents_dict) == 2
    assert (0, 1) in agents_dict and (0, 2) in agents_dict
    assert len(dataset.agents_tracked) == 2

    agents_dict = dataset.rasterise_agents_frame_batch(2)
    assert len(agents_dict) == 0
    assert len(dataset.agents_tracked) == 0


def test_simulation_agents_mock_disable(dmg: LocalDataManager, cfg: dict, tmp_path: Path) -> None:
    zarr_dataset = _mock_dataset()
    rasterizer = build_rasterizer(cfg, dmg)

    ego_dataset = EgoDataset(cfg, zarr_dataset, rasterizer)
    dataset = SimulationDataset(ego_dataset, [0], distance_th_close=10, disable_new_agents=True)

    # nothing should be tracked
    assert len(dataset.agents_tracked) == 0

    agents_dict = dataset.rasterise_agents_frame_batch(0)

    # only (0, 1) should be in
    assert len(agents_dict) == 1 and (0, 1) in agents_dict
    assert len(dataset.agents_tracked) == 1

    agents_dict = dataset.rasterise_agents_frame_batch(1)

    # again, only (0, 1) should be in
    assert len(agents_dict) == 1
    assert (0, 1) in agents_dict
    assert len(dataset.agents_tracked) == 1

    agents_dict = dataset.rasterise_agents_frame_batch(2)
    assert len(agents_dict) == 0
    assert len(dataset.agents_tracked) == 0


def test_simulation_agents_mock_insert(dmg: LocalDataManager, cfg: dict, tmp_path: Path) -> None:
    zarr_dataset = _mock_dataset()
    rasterizer = build_rasterizer(cfg, dmg)

    ego_dataset = EgoDataset(cfg, zarr_dataset, rasterizer)
    dataset = SimulationDataset(ego_dataset, [0], distance_th_close=10, disable_new_agents=True)

    _ = dataset.rasterise_agents_frame_batch(0)

    # insert (0, 1) in following frames
    next_agent = np.zeros(1, dtype=AGENT_DTYPE)
    next_agent["centroid"] = (-1, -1)
    next_agent["yaw"] = -0.5
    next_agent["track_id"] = 1
    next_agent["extent"] = (1, 1, 1)
    next_agent["label_probabilities"][:, 3] = 1

    for frame_idx in [1, 2, 3]:
        dataset.set_agents(frame_idx, {(0, 1): next_agent})

        agents_dict = dataset.rasterise_agents_frame_batch(frame_idx)
        assert len(agents_dict) == 1 and (0, 1) in agents_dict
        assert np.allclose(agents_dict[(0, 1)]["centroid"], (-1, -1))
        assert np.allclose(agents_dict[(0, 1)]["yaw"], -0.5)


def _mock_dataset() -> ChunkedDataset:
    zarr_dt = ChunkedDataset("")
    zarr_dt.scenes = np.zeros(1, dtype=SCENE_DTYPE)
    zarr_dt.scenes["frame_index_interval"][0] = (0, 4)

    zarr_dt.frames = np.zeros(4, dtype=FRAME_DTYPE)
    zarr_dt.frames["agent_index_interval"][0] = (0, 3)
    zarr_dt.frames["agent_index_interval"][1] = (3, 5)
    zarr_dt.frames["agent_index_interval"][2] = (5, 6)
    zarr_dt.frames["agent_index_interval"][3] = (6, 6)

    zarr_dt.agents = np.zeros(6, dtype=AGENT_DTYPE)
    # all agents except the first one are valid
    zarr_dt.agents["label_probabilities"][1:, 3] = 1
    # FRAME 0
    # second agent is close to ego and has id 1
    zarr_dt.agents["track_id"][1] = 1
    zarr_dt.agents["centroid"][1] = (1, 1)
    # third agent is too far and has id 2
    zarr_dt.agents["track_id"][2] = 2
    zarr_dt.agents["centroid"][2] = (100, 100)

    # FRAME 1
    # track 1 agent is still close to ego
    zarr_dt.agents["track_id"][3] = 1
    zarr_dt.agents["centroid"][3] = (1, 2)
    # track 2 is now close enough
    zarr_dt.agents["track_id"][4] = 2
    zarr_dt.agents["centroid"][4] = (1, 1)

    # FRAME 2
    # track 1 agent is far
    zarr_dt.agents["track_id"][5] = 1
    zarr_dt.agents["centroid"][5] = (100, 100)

    # FRAME 3 is empty

    zarr_dt.tl_faces = np.zeros(0, dtype=TL_FACE_DTYPE)

    return zarr_dt
