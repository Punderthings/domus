// Words the UI shows for data model objects. The API keeps the data model names
// (area, asset); change the display words here only, in one place.
// Decided by Shane on 2026-11-06: "Area" (Home Assistant's word, covers outdoor spaces) and
// "Device" (what homeowners say, covers furnaces as well as smart plugs).
export const terms = {
  property: 'Property',
  building: 'Building',
  buildings: 'Buildings',
  floor: 'Floor',
  area: 'Area',
  areas: 'Areas',
  device: 'Device',
  devices: 'Devices',
} as const;
