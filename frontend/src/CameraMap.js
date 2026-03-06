import React, { useEffect, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const activeIcon = new L.Icon({
  iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

const defaultIcon = new L.Icon({
  iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

function FlyToCenter({ center }) {
  const map = useMap();
  const prevCenter = useRef(center);

  useEffect(() => {
    const [prevLat, prevLng] = prevCenter.current;
    const [lat, lng] = center;
    if (prevLat !== lat || prevLng !== lng) {
      map.flyTo(center, map.getZoom(), { duration: 1.2, easeLinearity: 0.25 });
      prevCenter.current = center;
    }
  }, [center, map]);

  return null;
}

function InvalidateOnMount() {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => map.invalidateSize(), 100);
    return () => clearTimeout(timer);
  }, [map]);
  return null;
}

export default function CameraMap({ center, cameras, activeCamId, onSelectCamera }) {
  return (
    <MapContainer
      center={center}
      zoom={16}
      scrollWheelZoom={true}
      zoomControl={false}
      style={{ width: "100%", height: "100%" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/">OSM</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FlyToCenter center={center} />
      <InvalidateOnMount />
      {cameras.map((cam) => {
        if (!cam.location) return null;
        const isActive = cam.id === activeCamId;
        return (
          <Marker
            key={cam.id}
            position={[cam.location.lat, cam.location.lng]}
            icon={isActive ? activeIcon : defaultIcon}
            eventHandlers={{
              click: () => onSelectCamera(cam),
            }}
          >
            <Popup>
              <strong>{cam.name}</strong>
              <br />
              <span style={{ fontSize: "11px", opacity: 0.7 }}>
                {cam.location.lat.toFixed(4)}, {cam.location.lng.toFixed(4)}
              </span>
            </Popup>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
