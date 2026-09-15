import React, { forwardRef } from 'react';
import { Text as NativeText, TextInput as NativeTextInput, type TextProps, type TextInputProps } from 'react-native';
import { useTheme } from '../theme';

/** Body fonts are explicit: React Native Views do not inherit text styles. */
export const Text = forwardRef<React.ElementRef<typeof NativeText>, TextProps>(function ThemedText({ style, ...props }, ref) {
  const theme = useTheme();
  return <NativeText {...props} ref={ref} style={[{ fontFamily: theme.fontFamily }, style]} />;
});
export const TextInput = forwardRef<React.ElementRef<typeof NativeTextInput>, TextInputProps>(function ThemedTextInput({ style, ...props }, ref) {
  const theme = useTheme();
  return <NativeTextInput {...props} ref={ref} style={[{ fontFamily: theme.fontFamily }, style]} />;
});
