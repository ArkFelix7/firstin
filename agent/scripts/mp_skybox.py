"""Convert Matterport skybox (6 faces: 0=up,1..4=sides,5=down) to equirectangular JPEG."""
import numpy as np


def _dot(a, v):
    return a[..., 0] * v[0] + a[..., 1] * v[1] + a[..., 2] * v[2]
from PIL import Image

# face: (forward, right, up) unit vectors in world (x right, y up, z front)
F = {
    0: ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    1: ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    2: ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    3: ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
    4: ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    5: ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
}


def skybox_to_equirect(faces, out_w=2048):
    """faces: list of 6 PIL images (same square size). Returns PIL equirect image out_w x out_w/2."""
    out_h = out_w // 2
    arr = [np.asarray(f.convert("RGB")) for f in faces]
    n = arr[0].shape[0]
    lon = (np.arange(out_w) + 0.5) / out_w * 2 * np.pi - np.pi
    lat = np.pi / 2 - (np.arange(out_h) + 0.5) / out_h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    d = np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], -1)
    out = np.zeros((out_h, out_w, 3), np.uint8)
    best = np.full((out_h, out_w), -np.inf)
    idx = np.zeros((out_h, out_w), int)
    for k, (fw, _, _) in F.items():
        dp = _dot(d, fw)
        m = dp > best
        best[m] = dp[m]; idx[m] = k
    for k, (fw, rt, up) in F.items():
        m = idx == k
        dd = d[m]
        f = _dot(dd, fw)
        u = (_dot(dd, rt) / f + 1) / 2
        v = (-(_dot(dd, up)) / f + 1) / 2
        px = np.clip((u * n).astype(int), 0, n - 1)
        py = np.clip((v * n).astype(int), 0, n - 1)
        out[m] = arr[k][py, px]
    return Image.fromarray(out)
