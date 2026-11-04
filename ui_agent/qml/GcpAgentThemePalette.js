.pragma library
.import "GcpAgentThemeColorMath.js" as ColorMath
// Source-backed resolved defaults; unchanged protected aliases are frozen to original RGBA.
var SOURCE_THEME_SHA256 = "0c7ee3ca010b8a029d38e3d5d4d22d9b884d2b091fdbdc224cdc0ef6aeec0f85"
var SOURCE_DEFAULTS = {
  "primary": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 1
  },
  "primaryStrong": {
    "r": 0,
    "g": 0.7215686274509804,
    "b": 0.8588235294117647,
    "a": 1
  },
  "selectionGlow": {
    "r": 0.023529411764705882,
    "g": 0.7137254901960784,
    "b": 0.8313725490196079,
    "a": 1
  },
  "bgBase": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 1
  },
  "bgSurface": {
    "r": 0.0392156862745098,
    "g": 0.0392156862745098,
    "b": 0.0392156862745098,
    "a": 1
  },
  "bgPageSafety": {
    "r": 0.027450980392156862,
    "g": 0.043137254901960784,
    "b": 0.06274509803921569,
    "a": 1
  },
  "mediaVideoBackground": {
    "r": 0.0784313725490196,
    "g": 0.12156862745098039,
    "b": 0.1803921568627451,
    "a": 1
  },
  "bgCanvas": {
    "r": 0.0392156862745098,
    "g": 0.058823529411764705,
    "b": 0.07058823529411765,
    "a": 1
  },
  "neutral600": {
    "r": 0.4,
    "g": 0.4196078431372549,
    "b": 0.45098039215686275,
    "a": 1
  },
  "videoSignalBackground": {
    "r": 0.4,
    "g": 0.4196078431372549,
    "b": 0.45098039215686275,
    "a": 1
  },
  "panelFill": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.6
  },
  "panelFallbackFill": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.8
  },
  "panelPopupFill": {
    "r": 0.04,
    "g": 0.05,
    "b": 0.07,
    "a": 0.96
  },
  "panelBorder": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1
  },
  "bgCard": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.05
  },
  "bgInput": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.4
  },
  "borderDefault": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1
  },
  "textPrimary": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 1
  },
  "textSecondary": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.7
  },
  "textLabel": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.5
  },
  "textDescription": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.4
  },
  "textDisabled": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.3
  },
  "textOnPrimary": {
    "r": 0.023529411764705882,
    "g": 0.13333333333333333,
    "b": 0.16470588235294117,
    "a": 1
  },
  "bgToggleOff": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.2
  },
  "bgSettingRow": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.5
  },
  "statusSuccess": {
    "r": 0.2901960784313726,
    "g": 0.8705882352941177,
    "b": 0.5019607843137255,
    "a": 1
  },
  "statusWarning": {
    "r": 0.984313725490196,
    "g": 0.7490196078431373,
    "b": 0.1411764705882353,
    "a": 1
  },
  "statusCritical": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 1
  },
  "gpsNone": {
    "r": 1,
    "g": 0.3568627450980392,
    "b": 0.3568627450980392,
    "a": 1
  },
  "gpsWeak": {
    "r": 0.9647058823529412,
    "g": 0.7647058823529411,
    "b": 0.26666666666666666,
    "a": 1
  },
  "gpsGood": {
    "r": 0.0196078431372549,
    "g": 0.8745098039215686,
    "b": 0.4470588235294118,
    "a": 1
  },
  "gpsFixed": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 1
  },
  "telemetryMetricGreen": {
    "r": 0.13333333333333333,
    "g": 0.7725490196078432,
    "b": 0.3686274509803922,
    "a": 1
  },
  "telemetryMetricBlue": {
    "r": 0.23529411764705882,
    "g": 0.5490196078431373,
    "b": 0.9490196078431372,
    "a": 1
  },
  "telemetryMetricOrange": {
    "r": 0.9607843137254902,
    "g": 0.5019607843137255,
    "b": 0.0784313725490196,
    "a": 1
  },
  "bgElevated": {
    "r": 0.058823529411764705,
    "g": 0.06666666666666667,
    "b": 0.07450980392156863,
    "a": 1
  },
  "surface1": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.0392156862745098
  },
  "surface2": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.07058823529411765
  },
  "surface3": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.10196078431372549
  },
  "primarySubtle": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.12156862745098039
  },
  "primaryBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.6980392156862745
  },
  "iconDefault": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.5019607843137255
  },
  "lineSubtle": {
    "r": 0.5019607843137255,
    "g": 0.5411764705882353,
    "b": 0.5803921568627451,
    "a": 1
  },
  "neutral300": {
    "r": 0.6980392156862745,
    "g": 0.7215686274509804,
    "b": 0.7411764705882353,
    "a": 1
  },
  "neutral500": {
    "r": 0.5490196078431373,
    "g": 0.5686274509803921,
    "b": 0.5882352941176471,
    "a": 1
  },
  "mapBlock": {
    "r": 0.054901960784313725,
    "g": 0.12156862745098039,
    "b": 0.10588235294117647,
    "a": 0.7490196078431373
  },
  "hudPrimary": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 1
  },
  "hudSecondary": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.7215686274509804
  },
  "hudTape": {
    "r": 0.3803921568627451,
    "g": 0.4117647058823529,
    "b": 0.4392156862745098,
    "a": 1
  },
  "hudTarget": {
    "r": 1,
    "g": 0.4,
    "b": 0.8980392156862745,
    "a": 1
  },
  "statusInfo": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 1
  },
  "statusAck": {
    "r": 0.3764705882352941,
    "g": 0.6470588235294118,
    "b": 0.9803921568627451,
    "a": 1
  },
  "statusOffline": {
    "r": 0.3803921568627451,
    "g": 0.4117647058823529,
    "b": 0.4392156862745098,
    "a": 1
  },
  "statusDisabled": {
    "r": 0.25098039215686274,
    "g": 0.27058823529411763,
    "b": 0.2901960784313726,
    "a": 1
  },
  "statusSuccessSubtle": {
    "r": 0.2901960784313726,
    "g": 0.8705882352941177,
    "b": 0.5019607843137255,
    "a": 0.1411764705882353
  },
  "statusSuccessBorder": {
    "r": 0.2901960784313726,
    "g": 0.8705882352941177,
    "b": 0.5019607843137255,
    "a": 0.5019607843137255
  },
  "statusWarningSubtle": {
    "r": 0.984313725490196,
    "g": 0.7490196078431373,
    "b": 0.1411764705882353,
    "a": 0.1607843137254902
  },
  "statusWarningBorder": {
    "r": 0.984313725490196,
    "g": 0.7490196078431373,
    "b": 0.1411764705882353,
    "a": 0.45098039215686275
  },
  "statusCriticalSubtle": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.10196078431372549
  },
  "statusCriticalBorder": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.5019607843137255
  },
  "menuAccent": {
    "r": 0,
    "g": 0.8980392156862745,
    "b": 1,
    "a": 1
  },
  "menuBg": {
    "r": 0.03137254901960784,
    "g": 0.050980392156862744,
    "b": 0.07058823529411765,
    "a": 1
  },
  "menuSurface": {
    "r": 0.043137254901960784,
    "g": 0.06666666666666667,
    "b": 0.09019607843137255,
    "a": 1
  },
  "menuButtonDefaultBg": {
    "r": 0.054901960784313725,
    "g": 0.08235294117647059,
    "b": 0.10980392156862745,
    "a": 1
  },
  "menuButtonDefaultStroke": {
    "r": 0.3215686274509804,
    "g": 0.3843137254901961,
    "b": 0.4392156862745098,
    "a": 1
  },
  "menuButtonActiveBg": {
    "r": 0.027450980392156862,
    "g": 0.18823529411764706,
    "b": 0.22745098039215686,
    "a": 1
  },
  "menuButtonActiveStroke": {
    "r": 0,
    "g": 0.8980392156862745,
    "b": 1,
    "a": 1
  },
  "menuButtonFeaturedBg": {
    "r": 0.03137254901960784,
    "g": 0.7803921568627451,
    "b": 0.8627450980392157,
    "a": 1
  },
  "menuButtonFeaturedStroke": {
    "r": 0.47058823529411764,
    "g": 0.9450980392156862,
    "b": 1,
    "a": 1
  },
  "menuButtonFeaturedText": {
    "r": 0,
    "g": 0.0784313725490196,
    "b": 0.09803921568627451,
    "a": 1
  },
  "menuIconDefault": {
    "r": 0.8392156862745098,
    "g": 0.8784313725490196,
    "b": 0.9058823529411765,
    "a": 1
  },
  "menuTextPrimary": {
    "r": 0.9686274509803922,
    "g": 0.9803921568627451,
    "b": 0.9882352941176471,
    "a": 1
  },
  "menuTextSecondary": {
    "r": 0.7215686274509804,
    "g": 0.7686274509803922,
    "b": 0.807843137254902,
    "a": 1
  },
  "primaryHover": {
    "r": 0.1607843137254902,
    "g": 0.8784313725490196,
    "b": 0.9803921568627451,
    "a": 1
  },
  "primaryPressed": {
    "r": 0,
    "g": 0.6549019607843137,
    "b": 0.7607843137254902,
    "a": 1
  },
  "buttonSolidBg": {
    "r": 0.12941176470588237,
    "g": 0.1568627450980392,
    "b": 0.19607843137254902,
    "a": 1
  },
  "buttonSolidBorder": {
    "r": 0.4196078431372549,
    "g": 0.4627450980392157,
    "b": 0.5176470588235295,
    "a": 1
  },
  "buttonSolidHoverBg": {
    "r": 0.18823529411764706,
    "g": 0.22745098039215686,
    "b": 0.2784313725490196,
    "a": 1
  },
  "buttonSolidPressedBg": {
    "r": 0.0392156862745098,
    "g": 0.050980392156862744,
    "b": 0.06666666666666667,
    "a": 1
  },
  "buttonSolidPressedBorder": {
    "r": 0,
    "g": 0.7215686274509804,
    "b": 0.8588235294117647,
    "a": 1
  },
  "buttonGhostBg": {
    "r": 0.13,
    "g": 0.16,
    "b": 0.2,
    "a": 0.88
  },
  "dangerPressed": {
    "r": 0.35294117647058826,
    "g": 0.050980392156862744,
    "b": 0.06666666666666667,
    "a": 1
  },
  "controlBg": {
    "r": 0.03137254901960784,
    "g": 0.0392156862745098,
    "b": 0.047058823529411764,
    "a": 1
  },
  "controlHoverBg": {
    "r": 0.09803921568627451,
    "g": 0.10980392156862745,
    "b": 0.12941176470588237,
    "a": 1
  },
  "controlHoverBorder": {
    "r": 0.6039215686274509,
    "g": 0.6470588235294118,
    "b": 0.7019607843137254,
    "a": 1
  },
  "dangerFill": {
    "r": 0.2,
    "g": 0.03137254901960784,
    "b": 0.0392156862745098,
    "a": 1
  },
  "dangerFillHover": {
    "r": 0.2784313725490196,
    "g": 0.0392156862745098,
    "b": 0.050980392156862744,
    "a": 1
  },
  "dangerBorderHover": {
    "r": 1,
    "g": 0.32941176470588235,
    "b": 0.32941176470588235,
    "a": 1
  },
  "tabSelectedBg": {
    "r": 0.023529411764705882,
    "g": 0.1607843137254902,
    "b": 0.1803921568627451,
    "a": 1
  },
  "tabDefaultText": {
    "r": 0.5215686274509804,
    "g": 0.5686274509803921,
    "b": 0.611764705882353,
    "a": 1
  },
  "searchHoverBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.2
  },
  "searchFocusBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.6
  },
  "inputErrorBorder": {
    "r": 0.9490196078431372,
    "g": 0.23137254901960785,
    "b": 0.27058823529411763,
    "a": 1
  },
  "sliderRail": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1411764705882353
  },
  "sliderFillDisabled": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.25098039215686274
  },
  "dialogBg": {
    "r": 0.043137254901960784,
    "g": 0.058823529411764705,
    "b": 0.0784313725490196,
    "a": 0.9803921568627451
  },
  "dialogBorder": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.2
  },
  "dialogBodyText": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.8509803921568627
  },
  "scrim": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.47843137254901963
  },
  "badgePrimaryBg": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.14901960784313725
  },
  "badgeCriticalBg": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.14901960784313725
  },
  "toastProcessingBg": {
    "r": 0.054901960784313725,
    "g": 0.15294117647058825,
    "b": 0.16862745098039217,
    "a": 1
  },
  "toastProcessingBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.45098039215686275
  },
  "toastSuccessBg": {
    "r": 0.08627450980392157,
    "g": 0.1450980392156863,
    "b": 0.10588235294117647,
    "a": 1
  },
  "toastSuccessBorder": {
    "r": 0.2901960784313726,
    "g": 0.8705882352941177,
    "b": 0.5019607843137255,
    "a": 0.45098039215686275
  },
  "toastFailedBg": {
    "r": 0.14901960784313725,
    "g": 0.08235294117647059,
    "b": 0.08235294117647059,
    "a": 1
  },
  "toastFailedBorder": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.45098039215686275
  },
  "toastSubText": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.6
  },
  "authDim": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.6
  },
  "authFieldLabel": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.6509803921568628
  },
  "authFieldText": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.9490196078431372
  },
  "authFieldUnderline": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.34901960784313724
  },
  "authFieldUnderlineError": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.8
  },
  "authButtonText": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 1
  },
  "authBusyBg": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.1411764705882353
  },
  "authBusyBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.5019607843137255
  },
  "authFailedBg": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.1411764705882353
  },
  "authDisabledBg": {
    "r": 0.6,
    "g": 0.6,
    "b": 0.6,
    "a": 0.12156862745098039
  },
  "authDisabledBorder": {
    "r": 0.6,
    "g": 0.6,
    "b": 0.6,
    "a": 0.5019607843137255
  },
  "authDisabledText": {
    "r": 0.6,
    "g": 0.6,
    "b": 0.6,
    "a": 1
  },
  "homeStatusBarBg": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.5490196078431373
  },
  "homeStatusBarBorder": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1607843137254902
  },
  "homeChipBg": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.5019607843137255
  },
  "homeChipBorder": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1411764705882353
  },
  "homeDetailsBg": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.45098039215686275
  },
  "homeDivider": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.1803921568627451
  },
  "homeLabel": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.6
  },
  "homeUnit": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.5490196078431373
  },
  "homeDetailsText": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.8
  },
  "homeSubtitle": {
    "r": 0.6509803921568628,
    "g": 0.7294117647058823,
    "b": 0.7803921568627451,
    "a": 1
  },
  "homeAvatarBg": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.1803921568627451
  },
  "homeAlertBg": {
    "r": 0.9372549019607843,
    "g": 0.26666666666666666,
    "b": 0.26666666666666666,
    "a": 0.1803921568627451
  },
  "homeTileSecondaryBg": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.6509803921568628
  },
  "homeTileSecondaryBorder": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.2196078431372549
  },
  "homeTileText": {
    "r": 0,
    "g": 0.06274509803921569,
    "b": 0.09411764705882353,
    "a": 1
  },
  "homeTileSubText": {
    "r": 0,
    "g": 0.06274509803921569,
    "b": 0.09411764705882353,
    "a": 0.6980392156862745
  },
  "homeDimStart": {
    "r": 0.011764705882352941,
    "g": 0.0196078431372549,
    "b": 0.023529411764705882,
    "a": 0.6196078431372549
  },
  "homeDimMid1": {
    "r": 0.011764705882352941,
    "g": 0.0196078431372549,
    "b": 0.023529411764705882,
    "a": 0.1803921568627451
  },
  "homeDimMid2": {
    "r": 0.011764705882352941,
    "g": 0.0196078431372549,
    "b": 0.023529411764705882,
    "a": 0.10196078431372549
  },
  "homeDimEnd": {
    "r": 0.011764705882352941,
    "g": 0.0196078431372549,
    "b": 0.023529411764705882,
    "a": 0.47843137254901963
  },
  "homeScrimStrong": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.6980392156862745
  },
  "homeScrimBottom": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0.8
  },
  "homeScrimClear": {
    "r": 0,
    "g": 0,
    "b": 0,
    "a": 0
  },
  "optionMenuBg": {
    "r": 0.06274509803921569,
    "g": 0.06274509803921569,
    "b": 0.06274509803921569,
    "a": 1
  },
  "optionMenuSelectedBg": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.14901960784313725
  },
  "optionMenuSelectedBorder": {
    "r": 0,
    "g": 0.8274509803921568,
    "b": 0.9490196078431372,
    "a": 0.6
  },
  "optionMenuItemText": {
    "r": 1,
    "g": 1,
    "b": 1,
    "a": 0.8980392156862745
  },
  "flightModeSelectedBg": {
    "r": 0.0196078431372549,
    "g": 0.2235294117647059,
    "b": 0.2549019607843137,
    "a": 1
  },
  "missionPanelBg": {
    "r": 0.043137254901960784,
    "g": 0.058823529411764705,
    "b": 0.07450980392156863,
    "a": 1
  },
  "missionCardBg": {
    "r": 0.09019607843137255,
    "g": 0.10588235294117647,
    "b": 0.12156862745098039,
    "a": 1
  },
  "missionSelectedBg": {
    "r": 0.0392156862745098,
    "g": 0.16470588235294117,
    "b": 0.19607843137254902,
    "a": 1
  },
  "missionPropertyBg": {
    "r": 0.0392156862745098,
    "g": 0.10196078431372549,
    "b": 0.12941176470588237,
    "a": 1
  },
  "missionPropertyTileBg": {
    "r": 0.10588235294117647,
    "g": 0.16470588235294117,
    "b": 0.19215686274509805,
    "a": 1
  },
  "missionButtonBg": {
    "r": 0.10980392156862745,
    "g": 0.12549019607843137,
    "b": 0.1411764705882353,
    "a": 1
  },
  "opaqueDock": {
    "r": 0.0196078431372549,
    "g": 0.0196078431372549,
    "b": 0.0196078431372549,
    "a": 1
  },
  "opaqueBgCard": {
    "r": 0.08627450980392157,
    "g": 0.08627450980392157,
    "b": 0.08627450980392157,
    "a": 1
  },
  "opaqueBgInput": {
    "r": 0.027450980392156862,
    "g": 0.027450980392156862,
    "b": 0.027450980392156862,
    "a": 1
  },
  "opaqueBgPanel": {
    "r": 0.058823529411764705,
    "g": 0.06666666666666667,
    "b": 0.07450980392156863,
    "a": 1
  },
  "opaqueBorderDefault": {
    "r": 0.13725490196078433,
    "g": 0.13725490196078433,
    "b": 0.13725490196078433,
    "a": 1
  },
  "opaqueHudSecondary": {
    "r": 0,
    "g": 0.596078431372549,
    "b": 0.6823529411764706,
    "a": 1
  },
  "opaqueIconDefault": {
    "r": 0.5215686274509804,
    "g": 0.5215686274509804,
    "b": 0.5215686274509804,
    "a": 1
  },
  "opaqueMapBlock": {
    "r": 0.054901960784313725,
    "g": 0.12156862745098039,
    "b": 0.10588235294117647,
    "a": 1
  },
  "opaquePrimaryBorder": {
    "r": 0.011764705882352941,
    "g": 0.6078431372549019,
    "b": 0.6941176470588235,
    "a": 1
  },
  "opaquePrimarySubtle": {
    "r": 0.03529411764705882,
    "g": 0.13333333333333333,
    "b": 0.14901960784313725,
    "a": 1
  },
  "opaqueStatusCriticalBorder": {
    "r": 0.48627450980392156,
    "g": 0.15294117647058825,
    "b": 0.15294117647058825,
    "a": 1
  },
  "opaqueStatusCriticalSubtle": {
    "r": 0.12941176470588237,
    "g": 0.06274509803921569,
    "b": 0.06274509803921569,
    "a": 1
  },
  "opaqueStatusSuccessBorder": {
    "r": 0.16470588235294117,
    "g": 0.4549019607843137,
    "b": 0.27058823529411763,
    "a": 1
  },
  "opaqueStatusSuccessSubtle": {
    "r": 0.07450980392156863,
    "g": 0.1568627450980392,
    "b": 0.10588235294117647,
    "a": 1
  },
  "opaqueStatusWarningBorder": {
    "r": 0.4666666666666667,
    "g": 0.3607843137254902,
    "b": 0.08627450980392157,
    "a": 1
  },
  "opaqueStatusWarningSubtle": {
    "r": 0.19215686274509805,
    "g": 0.15294117647058825,
    "b": 0.06274509803921569,
    "a": 1
  },
  "opaqueSurface1": {
    "r": 0.10588235294117647,
    "g": 0.10588235294117647,
    "b": 0.10588235294117647,
    "a": 1
  },
  "opaqueSurface2": {
    "r": 0.12941176470588237,
    "g": 0.12941176470588237,
    "b": 0.12941176470588237,
    "a": 1
  },
  "opaqueSurface3": {
    "r": 0.16470588235294117,
    "g": 0.16470588235294117,
    "b": 0.16470588235294117,
    "a": 1
  },
  "opaqueTextDisabled": {
    "r": 0.3137254901960784,
    "g": 0.3137254901960784,
    "b": 0.3137254901960784,
    "a": 1
  },
  "opaqueTextMuted": {
    "r": 0.41568627450980394,
    "g": 0.41568627450980394,
    "b": 0.41568627450980394,
    "a": 1
  },
  "opaqueTextSecondary": {
    "r": 0.7137254901960784,
    "g": 0.7137254901960784,
    "b": 0.7137254901960784,
    "a": 1
  },
  "opaqueTextTertiary": {
    "r": 0.5215686274509804,
    "g": 0.5215686274509804,
    "b": 0.5215686274509804,
    "a": 1
  }
}
// Appended to generated source constants. AI recipe draft, not a ratified policy.
var GROUP_TOKENS = {
    accent: ["primary", "primaryStrong", "selectionGlow", "primarySubtle", "primaryBorder", "hudPrimary", "hudSecondary", "primaryHover", "primaryPressed"],
    background: ["bgBase", "bgSurface", "bgElevated", "bgPageSafety", "panelFill", "panelFallbackFill", "panelPopupFill", "bgCard", "bgInput", "bgSettingRow"],
    text: ["textPrimary", "textSecondary", "textLabel", "textDescription"]
}
var BASE_TOKEN = {accent: "primary", background: "bgBase", text: "textPrimary"}
var STATUS_TOKENS = ["statusSuccess", "statusWarning", "statusCritical", "gpsNone", "gpsWeak", "gpsGood"]
function own(o, key) { return Object.prototype.hasOwnProperty.call(o, key) }
function need(ok, why) { if (!ok) throw new Error(why) }
function copy(v) { return JSON.parse(JSON.stringify(v)) }
function object(v) { return v && typeof v === "object" && !Array.isArray(v) }
function checkedGroups(groups) {
    need(object(groups), "theme groups required")
    var out = {}, keys = Object.keys(groups).sort()
    need(keys.length <= 3, "bounded group map required")
    for (var i = 0; i < keys.length; ++i) {
        var key = keys[i]
        need(own(GROUP_TOKENS, key), "unknown or protected theme group")
        out[key] = ColorMath.actionColor(groups[key])
    }
    return out
}
function fingerprint(groups) { return JSON.stringify(checkedGroups(groups)) }
function sourceDefaults() { return copy(SOURCE_DEFAULTS) }
function tokenGroup(name) {
    var groups = Object.keys(GROUP_TOKENS)
    for (var i = 0; i < groups.length; ++i) if (GROUP_TOKENS[groups[i]].indexOf(name) >= 0) return groups[i]
    return null
}
// Retain each token's source H/S/L offset and exact source alpha. RGB output is
// quantized to bytes; alpha remains an unrounded real (e.g. Qt.rgba(...,0.05)).
// Background's black reference contributes no hue: it adopts the requested hue.
function materialize(groups) {
    groups = checkedGroups(groups)
    var palette = sourceDefaults(), keys = Object.keys(groups)
    for (var i = 0; i < keys.length; ++i) {
        var group = keys[i], base = ColorMath.hsl(ColorMath.rgbHex(SOURCE_DEFAULTS[BASE_TOKEN[group]]))
        var requested = ColorMath.hsl(groups[group]), names = GROUP_TOKENS[group]
        for (var j = 0; j < names.length; ++j) {
            var name = names[j], source = SOURCE_DEFAULTS[name]
            var reference = ColorMath.hsl(ColorMath.rgbHex(source))
            var hue = requested.h + (group === "background" || base.s === 0 ? 0 : reference.h - base.h)
            var saturation = ColorMath.clamp(requested.s + reference.s - base.s)
            // Neutral source backgrounds use the new background saturation.
            if (group === "background") saturation = requested.s
            var value = ColorMath.rgba(ColorMath.fromHsl(hue, saturation,
                ColorMath.clamp(requested.l + reference.l - base.l)))
            value.a = source.a
            palette[name] = value
        }
    }
    // Defaults are resolved first, never evaluated through mutable aliases.
    // In particular gpsFixed/statusInfo stay original cyan when primary changes.
    return palette
}
function checkedPairs(palette, pairs) {
    need(Array.isArray(pairs) && pairs.length > 0 && pairs.length <= 512, "host contrast pair inventory required")
    var seen = {}, rows = [], pass = true
    function token(name) {
        need(typeof name === "string" && own(palette, name), "unknown pair token")
        return ColorMath.checkedRgba(palette[name])
    }
    for (var i = 0; i < pairs.length; ++i) {
        var p = pairs[i]
        need(object(p) && typeof p.id === "string" && /^[A-Za-z0-9_.-]{1,96}$/.test(p.id) && !own(seen, p.id), "invalid pair id")
        seen[p.id] = true
        need(p.role === "normal" || p.role === "secondary", "host pair role required")
        need(Array.isArray(p.backgrounds) && p.backgrounds.length > 0 && p.backgrounds.length <= 32, "bounded background stack required")
        var bg = token(p.backgrounds[0])
        need(bg.a === 1, "opaque bottom background required; media backdrop must be measured separately")
        for (var j = 1; j < p.backgrounds.length; ++j) bg = ColorMath.composite(token(p.backgrounds[j]), bg)
        var fg = ColorMath.composite(token(p.foreground), bg), a = ColorMath.luminance(fg), b = ColorMath.luminance(bg)
        var ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), minimum = p.role === "normal" ? 4.5 : 3
        var ok = ratio >= minimum
        rows.push({id: p.id, ratio: ratio, minimum: minimum, pass: ok})
        if (!ok) pass = false
    }
    return {pass: pass, rows: rows, coverage: "declared-static-pairs-only"}
}
function policyKey(policy) {
    need(object(policy) && policy.sourceThemeSha256 === SOURCE_THEME_SHA256, "exact host theme identity required")
    need(policy.scope === "host-declared-static-pairs", "explicit limited pair scope required")
    need(ColorMath.finite(policy.minimumHueDistance) && policy.minimumHueDistance > 0 && policy.minimumHueDistance <= 180,
        "explicit host status hue distance required")
    need(ColorMath.finite(policy.relativeAmount) && policy.relativeAmount > 0 && policy.relativeAmount <= 1, "explicit host relative amount required")
    need(Array.isArray(policy.pairs) && policy.pairs.length > 0 && policy.pairs.length <= 512, "host pair inventory required")
    // Validate pair structure even when a subsequent search has no candidates.
    checkedPairs(SOURCE_DEFAULTS, policy.pairs)
    return JSON.stringify({source: policy.sourceThemeSha256, scope: policy.scope,
        hue: policy.minimumHueDistance, relativeAmount: policy.relativeAmount, pairs: policy.pairs})
}
function statusColors() { return STATUS_TOKENS.map(function(n) { return ColorMath.rgbHex(SOURCE_DEFAULTS[n]) }) }
function protectedUnchanged(palette) {
    need(object(palette) && Object.keys(palette).length === Object.keys(SOURCE_DEFAULTS).length, "complete palette required")
    for (var name in SOURCE_DEFAULTS) if (own(SOURCE_DEFAULTS, name)) {
        need(own(palette, name), "palette token missing")
        var value = ColorMath.checkedRgba(palette[name])
        if (tokenGroup(name) === null) {
            var source = SOURCE_DEFAULTS[name]
            need(value.r === source.r && value.g === source.g && value.b === source.b && value.a === source.a,
                "protected/default token changed: " + name)
        }
    }
    return true
}
function verify(groups, policy) {
    policyKey(policy)
    groups = checkedGroups(groups)
    var palette = materialize(groups)
    protectedUnchanged(palette)
    var contrast = checkedPairs(palette, policy.pairs)
    var safe = !own(groups, "accent") || ColorMath.safeAccent(groups.accent, statusColors(), policy.minimumHueDistance)
    return {pass: safe && contrast.pass, palette: palette, contrast: contrast, safeAccent: safe,
        coverage: "declared-static-pairs-only", sourceThemeSha256: SOURCE_THEME_SHA256}
}
function checkedAction(action) {
    need(object(action) && Object.keys(action).length === 2 && own(action, "group") && own(action, "color"), "group/color action only")
    need(typeof action.group === "string" && own(GROUP_TOKENS, action.group), "unknown or protected action group")
    return {group: action.group, color: ColorMath.actionColor(action.color)}
}
// The model may supply only action values. Policy/pair inventory and source identity
// belong to the host; this library never calls a model or applies application state.
function preview(currentGroups, action, policy) {
    currentGroups = checkedGroups(currentGroups); action = checkedAction(action)
    var identity = policyKey(policy)
    function trial(color) {
        var next = copy(currentGroups); next[action.group] = color
        return verify(next, policy).pass
    }
    var result = action.group === "accent" ? ColorMath.fitAccent(action.color, statusColors(), policy.minimumHueDistance, trial)
        : ColorMath.fitLightness(action.color, trial)
    if (!result.ok) return {kind: "unavailable", requested: action.color, group: action.group, reason: result.reason, checks: result.checks}
    var next = copy(currentGroups); next[action.group] = result.color
    var verified = verify(next, policy); need(verified.pass, "final palette recheck failed")
    return {kind: "confirm", action: action, requested: action.color, actual: result.color, adjusted: result.color !== action.color,
        groups: checkedGroups(next), basis: fingerprint(currentGroups), policyKey: identity, contrast: verified.contrast,
        checks: result.checks, coverage: verified.coverage, confirmationRequired: true}
}
function fromInput(currentGroups, group, input, policy) {
    need(typeof group === "string" && own(GROUP_TOKENS, group), "unknown input group")
    var parsed = ColorMath.parseInput(input), color
    if (parsed.kind === "color") color = parsed.color
    else if (parsed.kind === "relative") {
        var groups = checkedGroups(currentGroups)
        var base = own(groups, group) ? groups[group] : ColorMath.rgbHex(SOURCE_DEFAULTS[BASE_TOKEN[group]])
        // No fallback amount, including for an otherwise valid host policy.
        color = ColorMath.relativeColor(base, parsed.direction, policy && policy.relativeAmount)
    } else return {kind: "clarify", group: group, reason: parsed.reason, text: input}
    return preview(currentGroups, {group: group, color: color}, policy)
}
// Call immediately BEFORE State.beginGroup(), then commit exactly this group map
// inside State's transaction. It rechecks current state, host policy, proposal
// integrity and final contrast; it is not itself a State transaction or UI action.
function validatedCommit(currentGroups, proposal, policy, confirmed) {
    need(confirmed === true, "explicit confirmation required")
    need(object(proposal) && proposal.kind === "confirm" && proposal.confirmationRequired === true, "confirmation proposal required")
    need(proposal.basis === fingerprint(currentGroups), "stale theme basis")
    need(proposal.policyKey === policyKey(policy), "host theme policy changed")
    var again = preview(currentGroups, proposal.action, policy)
    need(again.kind === "confirm" && again.requested === proposal.requested && again.actual === proposal.actual &&
        fingerprint(again.groups) === fingerprint(proposal.groups), "proposal altered or no longer valid")
    return copy(again.groups)
}
