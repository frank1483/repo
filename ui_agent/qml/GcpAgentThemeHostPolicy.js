.pragma library
// Host-owned static inventory, never accepted from model output.
// Claude usage-scan roles are provisional; excludes blur over map/video.
var INVENTORY_SHA256 = "62ae604b1d4b482353055c90cdddc023fdf4a7f9bc75670fd6e87e8dcccb991e"
var SOURCE_THEME_SHA256 = "0c7ee3ca010b8a029d38e3d5d4d22d9b884d2b091fdbdc224cdc0ef6aeec0f85"
var PAIRS = [
  {
    "id": "textPrimary.bgBase",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase",
    "foreground": "primary",
    "backgrounds": [
      "bgBase"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFill",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFallbackFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFallbackFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFallbackFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFallbackFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFallbackFill",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelPopupFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelPopupFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelPopupFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelPopupFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelPopupFill",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.bgSettingRow",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.bgSettingRow",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.bgSettingRow",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.bgSettingRow",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.bgSettingRow",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFallbackFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFallbackFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFallbackFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFallbackFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFallbackFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFallbackFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFallbackFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFallbackFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFallbackFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFallbackFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.panelFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.panelFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.panelFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.panelFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.panelFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.missionPanelBg",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.missionPanelBg",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.missionPanelBg",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.missionPanelBg",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.missionPanelBg",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgBase.missionPanelBg.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgBase.missionPanelBg.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgBase.missionPanelBg.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgBase",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgBase.missionPanelBg.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgBase",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgBase.missionPanelBg.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgBase",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFill",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFallbackFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFallbackFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFallbackFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFallbackFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFallbackFill",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelPopupFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelPopupFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelPopupFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelPopupFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelPopupFill",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.bgSettingRow",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.bgSettingRow",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.bgSettingRow",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.bgSettingRow",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.bgSettingRow",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFallbackFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFallbackFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFallbackFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFallbackFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFallbackFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFallbackFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFallbackFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFallbackFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFallbackFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFallbackFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.panelFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.panelFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.panelFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.panelFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.panelFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.missionPanelBg",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.missionPanelBg",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.missionPanelBg",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.missionPanelBg",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.missionPanelBg",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgSurface.missionPanelBg.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgSurface.missionPanelBg.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgSurface.missionPanelBg.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgSurface.missionPanelBg.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgSurface.missionPanelBg.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgSurface",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFill",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFallbackFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFallbackFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFallbackFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFallbackFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFallbackFill",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelPopupFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelPopupFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelPopupFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelPopupFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelPopupFill",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.bgSettingRow",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.bgSettingRow",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.bgSettingRow",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.bgSettingRow",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.bgSettingRow",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFallbackFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFallbackFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFallbackFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFallbackFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFallbackFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFallbackFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFallbackFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFallbackFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFallbackFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFallbackFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.panelFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.panelFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.panelFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.panelFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.panelFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.missionPanelBg",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.missionPanelBg",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.missionPanelBg",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.missionPanelBg",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.missionPanelBg",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgPageSafety.missionPanelBg.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgPageSafety.missionPanelBg.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgPageSafety.missionPanelBg.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgPageSafety.missionPanelBg.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgPageSafety.missionPanelBg.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgPageSafety",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFill",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFallbackFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFallbackFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFallbackFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFallbackFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFallbackFill",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelPopupFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelPopupFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelPopupFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelPopupFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelPopupFill",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.bgSettingRow",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.bgSettingRow",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.bgSettingRow",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.bgSettingRow",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.bgSettingRow",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFallbackFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFallbackFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFallbackFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFallbackFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFallbackFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFallbackFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFallbackFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFallbackFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFallbackFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFallbackFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.panelFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.panelFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.panelFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.panelFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.panelFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.missionPanelBg",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.missionPanelBg",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.missionPanelBg",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.missionPanelBg",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.missionPanelBg",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgCanvas.missionPanelBg.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgCanvas.missionPanelBg.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgCanvas.missionPanelBg.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgCanvas.missionPanelBg.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgCanvas.missionPanelBg.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgCanvas",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFill",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFallbackFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFallbackFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFallbackFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFallbackFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFallbackFill",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelPopupFill",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelPopupFill",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelPopupFill"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelPopupFill",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelPopupFill",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelPopupFill",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelPopupFill"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.bgSettingRow",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.bgSettingRow",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "bgSettingRow"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.bgSettingRow",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.bgSettingRow",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.bgSettingRow",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "bgSettingRow"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFallbackFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFallbackFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFallbackFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFallbackFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFallbackFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFill.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFill.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFill.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFill.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFill.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFallbackFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFallbackFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFallbackFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFallbackFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFallbackFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFallbackFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.panelFill.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.panelFill.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.panelFill.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.panelFill.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.panelFill.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "panelFill",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.bgInput",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.bgInput",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "bgInput"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.bgInput",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.bgInput",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.bgInput",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "bgInput"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.missionPanelBg",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.missionPanelBg",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.missionPanelBg",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.missionPanelBg",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.missionPanelBg",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg"
    ],
    "role": "secondary"
  },
  {
    "id": "textPrimary.bgElevated.missionPanelBg.bgCard",
    "foreground": "textPrimary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textSecondary.bgElevated.missionPanelBg.bgCard",
    "foreground": "textSecondary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "normal"
  },
  {
    "id": "textLabel.bgElevated.missionPanelBg.bgCard",
    "foreground": "textLabel",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textDescription.bgElevated.missionPanelBg.bgCard",
    "foreground": "textDescription",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "primary.bgElevated.missionPanelBg.bgCard",
    "foreground": "primary",
    "backgrounds": [
      "bgElevated",
      "missionPanelBg",
      "bgCard"
    ],
    "role": "secondary"
  },
  {
    "id": "textOnPrimary.bgBase.primaryStrong",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgBase",
      "primaryStrong"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgSurface.primaryStrong",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgSurface",
      "primaryStrong"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgPageSafety.primaryStrong",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgPageSafety",
      "primaryStrong"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgCanvas.primaryStrong",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgCanvas",
      "primaryStrong"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgElevated.primaryStrong",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgElevated",
      "primaryStrong"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgBase.primaryHover",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgBase",
      "primaryHover"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgSurface.primaryHover",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgSurface",
      "primaryHover"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgPageSafety.primaryHover",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgPageSafety",
      "primaryHover"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgCanvas.primaryHover",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgCanvas",
      "primaryHover"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgElevated.primaryHover",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgElevated",
      "primaryHover"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgBase.primaryPressed",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgBase",
      "primaryPressed"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgSurface.primaryPressed",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgSurface",
      "primaryPressed"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgPageSafety.primaryPressed",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgPageSafety",
      "primaryPressed"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgCanvas.primaryPressed",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgCanvas",
      "primaryPressed"
    ],
    "role": "normal"
  },
  {
    "id": "textOnPrimary.bgElevated.primaryPressed",
    "foreground": "textOnPrimary",
    "backgrounds": [
      "bgElevated",
      "primaryPressed"
    ],
    "role": "normal"
  }
]
function pairs() { return JSON.parse(JSON.stringify(PAIRS)) }
