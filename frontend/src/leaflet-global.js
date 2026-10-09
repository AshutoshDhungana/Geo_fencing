// Leaflet-Geoman is a plain script that patches the global `L`, so expose Leaflet before importing it.
import L from 'leaflet'
window.L = L
