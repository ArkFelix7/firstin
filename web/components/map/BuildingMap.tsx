"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MLMap, Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Building } from "@/lib/types";

export type Basemap = "light" | "satellite";

const ACCENT = "#2554c7";

const STYLE = {
  version: 8 as const,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    light: {
      type: "raster" as const,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      maxzoom: 16,
      attribution: "Esri, HERE, Garmin, © OpenStreetMap contributors",
    },
    labels: {
      type: "raster" as const,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      maxzoom: 16,
    },
    satellite: {
      type: "raster" as const,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      maxzoom: 19,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    },
  },
  layers: [
    { id: "satellite", type: "raster" as const, source: "satellite", layout: { visibility: "none" as const }, paint: { "raster-saturation": -0.15 } },
    { id: "light", type: "raster" as const, source: "light" },
    { id: "labels", type: "raster" as const, source: "labels", paint: { "raster-opacity": 0.9 } },
  ],
};

const CLUSTER_LAYERS = ["clusters", "cluster-count", "points"];

/** HTML marker for featured buildings and the current selection (few at a time). */
function markerEl(b: Building, selected: boolean, labels: boolean) {
  const el = document.createElement("button");
  el.type = "button";
  el.setAttribute("aria-label", b.address);
  el.className = "fi-marker";
  el.innerHTML = `<span class="fi-core"></span>${labels || selected ? `<span class="fi-label">${b.address.split(",")[0]}</span>` : ""}`;
  el.dataset.selected = selected ? "1" : "0";
  el.dataset.featured = b.featured ? "1" : "0";
  return el;
}

export function BuildingMap({
  buildings,
  selectedId,
  onSelect,
  basemap,
  focus,
  showMarkers = true,
  showLabels = true,
  padRight = 0,
  flyKey = 0,
}: {
  buildings: Building[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  basemap: Basemap;
  focus: { city: string; nonce: number } | null;
  showMarkers?: boolean;
  showLabels?: boolean;
  padRight?: number;
  /** Increment to fly to the current selection (user-initiated selections only). */
  flyKey?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const [ready, setReady] = useState(false);
  const [zoomedIn, setZoomedIn] = useState(false); // featured labels only once zoomed in, to avoid collisions
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  // Everything not featured goes through the clustered GeoJSON source.
  const geojson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: buildings
        .filter((b) => !b.featured && Number.isFinite(b.lat) && Number.isFinite(b.lng))
        .map((b) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [b.lng, b.lat] },
          properties: { id: b.building_id },
        })),
    }),
    [buildings],
  );

  // init
  useEffect(() => {
    let cancelled = false;
    let map: MLMap | null = null;
    (async () => {
      const maplibregl = await import("maplibre-gl");
      maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");
      if (cancelled || !box.current) return;
      const m = new maplibregl.Map({
        container: box.current,
        style: STYLE,
        center: [-118.3, 34.05],
        zoom: 10,
        attributionControl: { compact: false },
        fadeDuration: 0,
      });
      m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
      m.on("load", () => {
        if (cancelled) return;
        m.addSource("bldg", { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true, clusterMaxZoom: 14, clusterRadius: 44 });
        m.addLayer({
          id: "clusters",
          type: "circle",
          source: "bldg",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#e4ebfa",
            "circle-opacity": 0.95,
            "circle-stroke-color": ACCENT,
            "circle-stroke-width": 1.5,
            "circle-radius": ["step", ["get", "point_count"], 13, 25, 16, 100, 20, 400, 25],
          },
        });
        m.addLayer({
          id: "cluster-count",
          type: "symbol",
          source: "bldg",
          filter: ["has", "point_count"],
          layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Open Sans Semibold"], "text-size": 12, "text-allow-overlap": true },
          paint: { "text-color": "#1d3f99" },
        });
        m.addLayer({
          id: "points",
          type: "circle",
          source: "bldg",
          filter: ["!", ["has", "point_count"]],
          paint: { "circle-color": "#5a6b8c", "circle-radius": 4.5, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 },
        });
        m.on("click", "clusters", async (e) => {
          const f = m.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0];
          if (!f) return;
          const src = m.getSource("bldg") as GeoJSONSource;
          const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id as number);
          m.easeTo({ center: (f.geometry as unknown as { coordinates: [number, number] }).coordinates, zoom: Math.min(zoom + 0.5, 17) });
        });
        m.on("click", "points", (e) => {
          const id = e.features?.[0]?.properties?.id;
          if (id) onSelectRef.current(String(id));
        });
        for (const l of ["clusters", "points"]) {
          m.on("mouseenter", l, () => (m.getCanvas().style.cursor = "pointer"));
          m.on("mouseleave", l, () => (m.getCanvas().style.cursor = ""));
        }
        m.on("zoomend", () => setZoomedIn(m.getZoom() >= 12));
        setZoomedIn(m.getZoom() >= 12);
        setReady(true);
      });
      map = m;
      mapRef.current = m;
    })();
    const markerMap = markers.current;
    return () => {
      cancelled = true;
      markerMap.forEach((mk) => mk.remove());
      markerMap.clear();
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  // clustered data
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("bldg") as GeoJSONSource | undefined)?.setData(geojson);
  }, [ready, geojson]);

  // layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const l of CLUSTER_LAYERS) map.setLayoutProperty(l, "visibility", showMarkers ? "visible" : "none");
  }, [ready, showMarkers]);

  // featured + selected HTML markers
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let cancelled = false;
    (async () => {
      const maplibregl = await import("maplibre-gl");
      if (cancelled) return;
      markers.current.forEach((m) => m.remove());
      markers.current.clear();
      const shown = buildings.filter((b) => (showMarkers && b.featured) || b.building_id === selectedId);
      for (const b of shown) {
        const el = markerEl(b, b.building_id === selectedId, showLabels && zoomedIn);
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          onSelectRef.current(b.building_id);
        });
        const m = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat([b.lng, b.lat]).addTo(map);
        markers.current.set(b.building_id, m);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, buildings, selectedId, showMarkers, showLabels, zoomedIn]);

  // basemap
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.setLayoutProperty("satellite", "visibility", basemap === "satellite" ? "visible" : "none");
    map.setLayoutProperty("light", "visibility", basemap === "light" ? "visible" : "none");
    map.setLayoutProperty("labels", "visibility", basemap === "light" ? "visible" : "none");
  }, [ready, basemap]);

  // fly to selection (only when the caller bumps flyKey)
  const selRef = useRef<{ id: string | null; list: Building[]; pad: number }>({ id: null, list: [], pad: 0 });
  useEffect(() => {
    selRef.current = { id: selectedId, list: buildings, pad: padRight };
  }, [selectedId, buildings, padRight]);
  useEffect(() => {
    const map = mapRef.current;
    const { id, list, pad } = selRef.current;
    if (!ready || !map || !id || !flyKey) return;
    const b = list.find((x) => x.building_id === id);
    // Shift the camera east by half the panel width so the building sits in the visible area.
    // (Web Mercator: 360 degrees of longitude span 512 * 2^zoom pixels.)
    const ZOOM = 17;
    if (b) map.flyTo({ center: [b.lng + ((pad / 2) * 360) / (512 * 2 ** ZOOM), b.lat], zoom: ZOOM, speed: 1.4, curve: 1.5, essential: true });
  }, [ready, flyKey]);

  // fit city: frame the featured buildings (the demo set), else everything in the city
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const inCity = buildings.filter((b) => b.city === focus.city);
    const featured = inCity.filter((b) => b.featured);
    const pts = featured.length >= 2 ? featured : inCity;
    if (!pts.length) return;
    if (pts.length === 1) {
      map.flyTo({ center: [pts[0].lng, pts[0].lat], zoom: 13, speed: 1.6 });
      return;
    }
    const lngs = pts.map((p) => p.lng);
    const lats = pts.map((p) => p.lat);
    map.fitBounds(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: { top: 100, bottom: 100, left: 280, right: 120 + padRight }, maxZoom: 14, duration: 1200 },
    );
  }, [ready, focus, buildings, padRight]);

  return (
    <div className="relative h-full w-full">
      <div ref={box} className="h-full w-full" />
      <style>{`
        .fi-marker{width:16px;height:16px;border:0;background:none;padding:0;cursor:pointer}
        .fi-core{position:absolute;inset:0;border-radius:999px;background:var(--accent);border:2.5px solid #fff;box-shadow:0 1px 3px rgba(16,24,40,.45)}
        .fi-marker[data-selected="1"]{width:22px;height:22px;z-index:2}
        .fi-marker[data-selected="1"] .fi-core{background:var(--fg);border:3px solid #fff;box-shadow:0 0 0 2px var(--accent),0 1px 4px rgba(16,24,40,.5)}
        .fi-label{position:absolute;left:calc(100% + 6px);top:50%;transform:translateY(-50%);white-space:nowrap;font:600 12px/16px var(--font-sans);color:var(--fg);background:#fff;border:1px solid var(--line-strong);padding:2px 6px;border-radius:3px;pointer-events:none;box-shadow:0 1px 2px rgba(16,24,40,.2)}
        .fi-marker[data-selected="1"] .fi-label{background:var(--fg);color:#fff;border-color:var(--fg)}
      `}</style>
    </div>
  );
}
