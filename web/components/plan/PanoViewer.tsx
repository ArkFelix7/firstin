"use client";

import "@photo-sphere-viewer/core/index.css";
import "@photo-sphere-viewer/markers-plugin/index.css";
import { useEffect, useRef, useState } from "react";

type BBox = [number, number, number, number];

/** Normalize an equirect bbox (pixels on a 2048x1024 pano, or 0 to 1) to 0 to 1. */
function normBox(b: BBox, w = 2048, h = 1024): BBox {
  return b.every((n) => n <= 1.0001) ? b : [b[0] / w, b[1] / h, b[2] / w, b[3] / h];
}

const toYaw = (x: number) => (x - 0.5) * 2 * Math.PI;
const toPitch = (y: number) => (0.5 - y) * Math.PI;

/** Rectangle on the equirect image → yaw/pitch polygon (edges sampled so it curves correctly). */
function polygon(b: BBox): Array<[number, number]> {
  const [x0, y0, x1, y1] = b;
  const pts: Array<[number, number]> = [];
  const N = 10;
  for (let i = 0; i <= N; i++) pts.push([toYaw(x0 + ((x1 - x0) * i) / N), toPitch(y0)]);
  for (let i = 1; i <= N; i++) pts.push([toYaw(x1), toPitch(y0 + ((y1 - y0) * i) / N)]);
  for (let i = 1; i <= N; i++) pts.push([toYaw(x1 - ((x1 - x0) * i) / N), toPitch(y1)]);
  for (let i = 1; i < N; i++) pts.push([toYaw(x0), toPitch(y1 - ((y1 - y0) * i) / N)]);
  return pts;
}

export function PanoViewer({ url, bbox, label, imgW, imgH }: { url: string; bbox: BBox | null; label?: string; imgW?: number; imgH?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const bboxKey = bbox ? bbox.join(",") : "";

  useEffect(() => {
    const bbox = bboxKey ? (bboxKey.split(",").map(Number) as BBox) : null;
    let viewer: { destroy: () => void } | null = null;
    let cancelled = false;
    (async () => {
      const [{ Viewer }, { MarkersPlugin }] = await Promise.all([import("@photo-sphere-viewer/core"), import("@photo-sphere-viewer/markers-plugin")]);
      if (cancelled || !box.current) return;
      const b = bbox ? normBox(bbox, imgW ?? 2048, imgH ?? 1024) : null;
      const cx = b ? (b[0] + b[2]) / 2 : 0.5;
      const cy = b ? (b[1] + b[3]) / 2 : 0.5;
      const yaw = toYaw(cx);
      const pitch = Math.max(-1.2, Math.min(1.2, toPitch(cy)));
      const v = new Viewer({
        container: box.current,
        panorama: url,
        defaultYaw: yaw - 0.9,
        defaultPitch: pitch * 0.4,
        defaultZoomLvl: 10,
        navbar: ["zoom", "fullscreen"],
        loadingTxt: "",
        mousewheelCtrlKey: false,
        touchmoveTwoFingers: false,
        plugins: [
          [
            MarkersPlugin,
            {
              markers: b
                ? [
                    {
                      id: "cite",
                      polygon: polygon(b),
                      svgStyle: { fill: "rgba(61,123,255,0.12)", stroke: "#3d7bff", strokeWidth: "2px" },
                      tooltip: label ? { content: label, position: "top center" } : undefined,
                    },
                  ]
                : [],
            },
          ],
        ],
      });
      viewer = v;
      v.addEventListener("ready", () => {
        if (cancelled) return;
        setState("ready");
        // fly-in to the cited region
        v.animate({ yaw, pitch, zoom: b ? 45 : 20, speed: 2400 });
      }, { once: true });
      v.addEventListener("panorama-error", () => !cancelled && setState("error"));
    })().catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
      viewer?.destroy();
    };
  }, [url, bboxKey, label, imgW, imgH]);

  return (
    <div className="relative aspect-[4/3] w-full bg-muted">
      <div ref={box} className="absolute inset-0" />
      {state === "loading" && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-fg-3">Loading panorama</div>
      )}
      {state === "error" && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-fg-3">Panorama unavailable</div>
      )}
    </div>
  );
}
