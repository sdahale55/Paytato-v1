import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import TextInput from 'ink-text-input';

export interface FormData {
  requirements: string;
  budget: string;
  domain: string;
  instructions: string;
}

interface InputFormProps {
  onSubmit: (data: FormData) => void;
  initialData?: Partial<FormData>;
}

type Field = 'requirements' | 'budget' | 'domain' | 'instructions';

const FIELDS: { key: Field; label: string; placeholder: string; required?: boolean }[] = [
  { 
    key: 'requirements', 
    label: 'Shopping Requirements', 
    placeholder: 'e.g., "wireless mouse under $50, mechanical keyboard"',
    required: true,
  },
  { 
    key: 'budget', 
    label: 'Budget (optional)', 
    placeholder: 'e.g., "$200" or leave empty for no limit',
  },
  { 
    key: 'domain', 
    label: 'Store URL (optional)', 
    placeholder: 'Default: https://joy-buy-test.lovable.app',
  },
  { 
    key: 'instructions', 
    label: 'Custom Instructions (optional)', 
    placeholder: 'e.g., "Prefer brand X, avoid refurbished items"',
  },
];

export function InputForm({ onSubmit, initialData = {} }: InputFormProps) {
  const [formData, setFormData] = useState<FormData>({
    requirements: initialData.requirements || '',
    budget: initialData.budget || '',
    domain: initialData.domain || '',
    instructions: initialData.instructions || '',
  });
  const [activeField, setActiveField] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useInput((input, key) => {
    if (key.return) {
      handleSubmitField();
    } else if (key.upArrow && activeField > 0) {
      setActiveField(activeField - 1);
      setError(null);
    } else if (key.downArrow && activeField < FIELDS.length - 1) {
      setActiveField(activeField + 1);
      setError(null);
    } else if (key.tab) {
      if (key.shift && activeField > 0) {
        setActiveField(activeField - 1);
      } else if (!key.shift && activeField < FIELDS.length - 1) {
        setActiveField(activeField + 1);
      }
      setError(null);
    }
  });

  const handleSubmitField = () => {
    const currentField = FIELDS[activeField];
    
    // Validate required fields
    if (currentField.required && !formData[currentField.key].trim()) {
      setError(`${currentField.label} is required`);
      return;
    }

    // Move to next field or submit
    if (activeField < FIELDS.length - 1) {
      setActiveField(activeField + 1);
      setError(null);
    } else {
      // Final validation
      if (!formData.requirements.trim()) {
        setError('Shopping Requirements is required');
        setActiveField(0);
        return;
      }
      onSubmit(formData);
    }
  };

  const handleChange = (value: string) => {
    const field = FIELDS[activeField].key;
    setFormData(prev => ({ ...prev, [field]: value }));
    setError(null);
  };

  return (
    <Box flexDirection="column" gap={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">Enter Shopping Details</Text>
      </Box>

      {FIELDS.map((field, index) => {
        const isActive = index === activeField;
        const value = formData[field.key];
        
        return (
          <Box key={field.key} flexDirection="column">
            <Box>
              <Text color={isActive ? 'green' : 'white'} bold={isActive}>
                {isActive ? '> ' : '  '}
                {field.label}
                {field.required && <Text color="red">*</Text>}
              </Text>
            </Box>
            
            <Box marginLeft={4}>
              {isActive ? (
                <Box>
                  <Text color="gray">[</Text>
                  <TextInput
                    value={value}
                    onChange={handleChange}
                    placeholder={field.placeholder}
                  />
                  <Text color="gray">]</Text>
                </Box>
              ) : (
                <Text dimColor={!value}>
                  {value || field.placeholder}
                </Text>
              )}
            </Box>
          </Box>
        );
      })}

      {error && (
        <Box marginTop={1} marginLeft={2}>
          <Text color="red">{error}</Text>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column" marginLeft={2}>
        <Text dimColor>
          Press <Text color="green">Enter</Text> to continue,{' '}
          <Text color="blue">Up/Down</Text> to navigate
        </Text>
        {activeField === FIELDS.length - 1 && formData.requirements && (
          <Text color="green" bold>
            Press Enter to start the shopping agent
          </Text>
        )}
      </Box>
    </Box>
  );
}
