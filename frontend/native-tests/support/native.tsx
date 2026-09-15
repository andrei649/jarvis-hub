import React from 'react';
const listeners = new Set<(state: string) => void>();
export const AppState = { currentState: 'active', addEventListener: (_: string, listener: (state: string) => void) => {
  listeners.add(listener); return { remove: () => listeners.delete(listener) };
} };
export function foreground(state: string) { AppState.currentState = state; listeners.forEach(listener => listener(state)); }
export const Platform = { OS: 'ios', select: (values: Record<string, unknown>) => values.ios ?? values.default };
export const StyleSheet = { create: (styles: unknown) => styles, flatten: (style: any): any => Array.isArray(style) ? Object.assign({}, ...style.map(StyleSheet.flatten)) : style || {} };
export const Linking = { openURL: async () => {} };
const host = (tag: string) => React.forwardRef<any, any>(({ children, style, onPress, onChangeText, testID, accessibilityLabel, ...rest }, ref) => {
  const flat = StyleSheet.flatten(style);
  const props: any = { ref, 'data-testid': testID, 'aria-label': accessibilityLabel, 'data-native-style': JSON.stringify(flat), onClick: onPress };
  for (const key of ['value', 'placeholder', 'disabled']) if (key in rest) props[key] = rest[key];
  if (onChangeText) props.onChange = (event: any) => onChangeText(event.target.value);
  return React.createElement(tag, props, tag === 'input' ? undefined : children);
});
export const View = host('div'), Text = host('span'), TextInput = host('input'), Pressable = host('button');
export const SafeAreaView = View, ScrollView = View, KeyboardAvoidingView = View, ActivityIndicator = View, RefreshControl = View;
export const Modal = ({visible, children}:any) => visible ? <div>{children}</div> : null;
export const FlatList = ({data,renderItem,ListEmptyComponent}:any) => <div>{data?.length ? data.map((item:any,index:number)=><React.Fragment key={index}>{renderItem({item,index})}</React.Fragment>) : typeof ListEmptyComponent === 'function' ? <ListEmptyComponent/> : ListEmptyComponent}</div>;
export const Alert = {alert: () => {}}, Image = host('img');
