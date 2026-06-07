import React from 'react';
import { Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from '../theme';
import { parseMarkdown, type Block, type Inline } from './parse';

/** Render assistant Markdown to React Native nodes. */
export function Markdown({ text, color }: { text: string; color?: string }) {
  const blocks = React.useMemo(() => parseMarkdown(text), [text]);
  const base = color ?? theme.text;
  return (
    <View>
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} color={base} />
      ))}
    </View>
  );
}

function BlockView({ block, color }: { block: Block; color: string }) {
  switch (block.type) {
    case 'code':
      return (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.codeBlock}
          contentContainerStyle={styles.codeBlockContent}
        >
          <Text style={styles.codeText}>{block.text}</Text>
        </ScrollView>
      );
    case 'heading': {
      const size = HEADING_SIZES[block.level] ?? 15;
      return (
        <Text style={[styles.heading, { fontSize: size, color }]}>
          <InlineRun nodes={block.inline} color={color} />
        </Text>
      );
    }
    case 'list':
      return (
        <View style={styles.list}>
          {block.items.map((item, idx) => (
            <View key={idx} style={styles.listItem}>
              <Text style={[styles.bullet, { color: theme.accent }]}>
                {block.ordered ? `${idx + 1}.` : '•'}
              </Text>
              <Text style={[styles.paragraph, styles.listText, { color }]}>
                <InlineRun nodes={item} color={color} />
              </Text>
            </View>
          ))}
        </View>
      );
    case 'quote':
      return (
        <View style={styles.quote}>
          <Text style={[styles.paragraph, styles.quoteText, { color: theme.textDim }]}>
            <InlineRun nodes={block.inline} color={theme.textDim} />
          </Text>
        </View>
      );
    case 'paragraph':
    default:
      return (
        <Text style={[styles.paragraph, { color }]}>
          <InlineRun nodes={block.inline} color={color} />
        </Text>
      );
  }
}

function InlineRun({ nodes, color }: { nodes: Inline[]; color: string }) {
  return (
    <>
      {nodes.map((node, i) => (
        <InlineNode key={i} node={node} color={color} />
      ))}
    </>
  );
}

function InlineNode({ node, color }: { node: Inline; color: string }) {
  switch (node.type) {
    case 'text':
      return <Text style={{ color }}>{node.text}</Text>;
    case 'bold':
      return (
        <Text style={styles.bold}>
          <InlineRun nodes={node.children} color={color} />
        </Text>
      );
    case 'italic':
      return (
        <Text style={styles.italic}>
          <InlineRun nodes={node.children} color={color} />
        </Text>
      );
    case 'code':
      return <Text style={styles.inlineCode}>{node.text}</Text>;
    case 'link':
      return (
        <Text style={styles.link} onPress={() => void Linking.openURL(node.href).catch(() => {})}>
          {node.text}
        </Text>
      );
    default:
      return null;
  }
}

const HEADING_SIZES: Record<number, number> = { 1: 22, 2: 20, 3: 18, 4: 16, 5: 15, 6: 14 };

const styles = StyleSheet.create({
  paragraph: { fontSize: 15, lineHeight: 21, marginVertical: 2 },
  heading: { fontWeight: '700', marginTop: 6, marginBottom: 2 },
  bold: { fontWeight: '700' },
  italic: { fontStyle: 'italic' },
  inlineCode: {
    fontFamily: 'monospace',
    fontSize: 14,
    color: theme.accent,
    backgroundColor: theme.surfaceAlt,
  },
  codeBlock: {
    backgroundColor: theme.bg,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: theme.border,
    marginVertical: 6,
  },
  codeBlockContent: { padding: 10 },
  codeText: { fontFamily: 'monospace', fontSize: 13, lineHeight: 19, color: theme.text },
  list: { marginVertical: 2 },
  listItem: { flexDirection: 'row', alignItems: 'flex-start', marginVertical: 1 },
  bullet: { width: 22, fontSize: 15, lineHeight: 21, fontWeight: '700' },
  listText: { flex: 1 },
  quote: {
    borderLeftWidth: 3,
    borderLeftColor: theme.accentDim,
    paddingLeft: 10,
    marginVertical: 4,
  },
  quoteText: { fontStyle: 'italic' },
  link: { color: theme.accent, textDecorationLine: 'underline' },
});
