import React from 'react';

const element = (tag: string) => ({ children, accessible: _accessible, ...props }: any) => React.createElement(tag, props, children);
const Svg = element('svg');
export const Circle = element('circle');
export const Ellipse = element('ellipse');
export const Line = element('line');
export default Svg;
