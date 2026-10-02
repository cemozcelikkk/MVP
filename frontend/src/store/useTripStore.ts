import { create } from "zustand";
import type { SpotFeature, TripRoute } from "../lib/api";
interface TripState {
  isOpen:boolean; pendingSpot:SpotFeature|null; route:TripRoute["geometry"]|null;
  open:(spot?:SpotFeature)=>void;close:()=>void;showRoute:(route:TripRoute["geometry"])=>void;reset:()=>void;
}
export const useTripStore=create<TripState>(set=>({
  isOpen:false,pendingSpot:null,route:null,
  open:(spot)=>set({isOpen:true,pendingSpot:spot??null}),
  close:()=>set({isOpen:false,pendingSpot:null}),
  showRoute:(route)=>set({route,isOpen:false,pendingSpot:null}),
  reset:()=>set({isOpen:false,pendingSpot:null,route:null}),
}));
