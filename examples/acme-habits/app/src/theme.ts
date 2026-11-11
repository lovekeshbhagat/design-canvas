// Acme Habits: a made-up sample app used to test design-canvas.
// Every value below is mirrored in ../design.json with a `src` pointer,
// so `build.py --check` can prove the guide still matches the code.

export const light = {
  bg: '#FFFFFF', // screen background
  surface: '#F5F6F8', // cards, sheets
  surfaceRaised: '#ECEEF2', // pressed rows, inputs
  text: '#111318',
  textMuted: '#5F6672',
  primary: '#3B5BFD', // buttons, progress, focus
  onPrimary: '#FFFFFF',
  success: '#1F9D55',
  danger: '#D93025',
  border: '#E3E6EB',
  scrim: 'rgba(0, 0, 0, 0.45)',
}

export const dark: typeof light = {
  bg: '#0E0F12',
  surface: '#17191D',
  surfaceRaised: '#22252B',
  text: '#F2F3F5',
  textMuted: '#9AA0AA',
  primary: '#6F86FF',
  onPrimary: '#0E0F12',
  success: '#3CCB7F',
  danger: '#FF6B5E',
  border: '#2B2E35',
  scrim: 'rgba(0, 0, 0, 0.45)',
}

export const fontFamily = {
  regular: 'Inter_400Regular',
  medium: 'Inter_500Medium',
  semibold: 'Inter_600SemiBold',
  bold: 'Inter_700Bold',
}

export const type = {
  display: { fontFamily: fontFamily.bold, fontSize: 32, lineHeight: 38, letterSpacing: -0.5 },
  title: { fontFamily: fontFamily.semibold, fontSize: 22, lineHeight: 28, letterSpacing: -0.2 },
  heading: { fontFamily: fontFamily.semibold, fontSize: 17, lineHeight: 22 },
  body: { fontFamily: fontFamily.regular, fontSize: 16, lineHeight: 22 },
  label: { fontFamily: fontFamily.medium, fontSize: 14, lineHeight: 18 },
  caption: { fontFamily: fontFamily.regular, fontSize: 12, lineHeight: 16 },
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, gutter: 20 }

export const radius = { sm: 6, md: 10, card: 16, pill: 999 }

export const shadow = {
  card: { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.08, shadowRadius: 8, elevation: 2 },
  sheet: { shadowColor: '#000', shadowOffset: { width: 0, height: -4 }, shadowOpacity: 0.16, shadowRadius: 24, elevation: 8 },
}

export const motion = {
  duration: { fast: 150, base: 220, slow: 320 },
  spring: { gentle: { damping: 18, stiffness: 180, mass: 1 } },
}
