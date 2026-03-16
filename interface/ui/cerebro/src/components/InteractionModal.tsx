/**
 * NEXUS CEREBRO Interaction Modal
 * Handles ask/confirm/choose interactions from agents
 */
import { useState } from 'react';
import { useInteractionStore } from '../stores/interactionStore';
import type { PendingInteraction } from '../types/api';

interface Props {
  interaction: PendingInteraction;
  onClose: () => void;
}

export function InteractionModal({ interaction, onClose }: Props) {
  const [response, setResponse] = useState(interaction.default || '');
  const [submitting, setSubmitting] = useState(false);
  const reply = useInteractionStore((s) => s.reply);
  const error = useInteractionStore((s) => s.error);
  const clearError = useInteractionStore((s) => s.clearError);

  const handleSubmit = async () => {
    setSubmitting(true);
    clearError();

    let value: string | boolean | number = response;

    // Convert confirm responses to boolean
    if (interaction.interaction_type === 'confirm') {
      value = response.toLowerCase() === 'yes' || response === 'true';
    }

    const success = await reply(interaction.request_id, value);
    if (success) {
      onClose();
    }
    setSubmitting(false);
  };

  const handleConfirmClick = (answer: 'yes' | 'no') => {
    setResponse(answer);
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-nexus-dark rounded-xl border border-gray-700 shadow-2xl max-w-md w-full animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <span className="text-warning text-lg">
              {interaction.interaction_type === 'confirm' ? '?' :
               interaction.interaction_type === 'choose' ? '...' : '>_'}
            </span>
            <h3 className="text-lg font-semibold text-white">
              {interaction.interaction_type === 'confirm' ? 'Confirmation Required' :
               interaction.interaction_type === 'choose' ? 'Select Option' :
               'Input Required'}
            </h3>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-4">
          <p className="text-gray-300 mb-4 whitespace-pre-wrap">{interaction.prompt}</p>

          {/* Input based on type */}
          {interaction.interaction_type === 'choose' && interaction.choices ? (
            <select
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              disabled={submitting}
              className="w-full px-4 py-2 rounded-lg bg-nexus-darker border border-gray-600
                         text-white focus:outline-none focus:ring-2 focus:ring-primary
                         disabled:opacity-50"
            >
              <option value="">Select an option...</option>
              {interaction.choices.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          ) : interaction.interaction_type === 'confirm' ? (
            <div className="flex gap-3">
              <button
                onClick={() => handleConfirmClick('yes')}
                disabled={submitting}
                className={`flex-1 py-3 rounded-lg font-medium transition-colors
                  ${response === 'yes'
                    ? 'bg-secondary text-white'
                    : 'bg-nexus-darker text-gray-300 hover:bg-gray-700'}`}
              >
                Yes
              </button>
              <button
                onClick={() => handleConfirmClick('no')}
                disabled={submitting}
                className={`flex-1 py-3 rounded-lg font-medium transition-colors
                  ${response === 'no'
                    ? 'bg-danger text-white'
                    : 'bg-nexus-darker text-gray-300 hover:bg-gray-700'}`}
              >
                No
              </button>
            </div>
          ) : (
            <input
              type="text"
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              disabled={submitting}
              placeholder={interaction.default || 'Enter your response...'}
              className="w-full px-4 py-2 rounded-lg bg-nexus-darker border border-gray-600
                         text-white placeholder-gray-500
                         focus:outline-none focus:ring-2 focus:ring-primary
                         disabled:opacity-50"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && response) {
                  handleSubmit();
                }
              }}
            />
          )}

          {/* Error */}
          {error && (
            <p className="mt-3 text-sm text-danger">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-700 flex gap-3">
          <button
            onClick={onClose}
            disabled={submitting}
            className="flex-1 py-2 rounded-lg font-medium text-gray-300
                       bg-nexus-darker hover:bg-gray-700
                       disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !response}
            className="flex-1 py-2 rounded-lg font-medium text-white
                       bg-primary hover:bg-blue-600
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Submitting...' : 'Submit'}
          </button>
        </div>
      </div>
    </div>
  );
}
