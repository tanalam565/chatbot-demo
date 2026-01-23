// frontend/src/components/ChatInterface.js - FIXED CLEANUP

import React, { useState, useRef, useEffect } from 'react';
import { sendMessage } from '../services/api';
import './ChatInterface.css';

function ChatInterface() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    return `session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
  });
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Log session ID for debugging
  useEffect(() => {
    console.log('🔑 Session ID:', sessionId);
  }, [sessionId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // FIXED: Only cleanup on component unmount (no dependencies!)
  useEffect(() => {
    const cleanupSession = async () => {
      if (uploadedFiles.length > 0 && sessionId) {
        console.log('🗑️ Cleaning up session on unmount:', sessionId);
        try {
          await fetch(
            `${process.env.REACT_APP_API_URL}/cleanup-session`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
              },
              body: JSON.stringify({ session_id: sessionId }),
              keepalive: true
            }
          );
        } catch (error) {
          console.error('Cleanup error:', error);
        }
      }
    };

    // Only cleanup on window close (not on refresh)
    const handleBeforeUnload = (e) => {
      if (uploadedFiles.length > 0) {
        cleanupSession();
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    // Cleanup ONLY when component unmounts (page close)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      // Only cleanup if truly unmounting (not on every render)
      cleanupSession();
    };
  }, []); // ← FIXED: Empty dependency array!

  const handleCopy = (text, index) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    }).catch(err => {
      console.error('Failed to copy:', err);
    });
  };

  const handleFileUpload = async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setUploading(true);
    const uploadResults = [];

    console.log('📤 Uploading files with session ID:', sessionId);

    try {
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);

        console.log('📤 Uploading:', file.name, 'with session:', sessionId);

        const response = await fetch(
          `${process.env.REACT_APP_API_URL}/upload`,
          {
            method: 'POST',
            headers: {
              'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
            },
            body: formData
          }
        );

        if (response.ok) {
          const result = await response.json();
          console.log('✅ Upload successful. Backend returned session:', result.session_id);
          
          uploadResults.push({
            name: file.name,
            success: true,
            pages: result.pages_extracted
          });
        } else {
          uploadResults.push({
            name: file.name,
            success: false
          });
        }
      }

      setUploadedFiles(prev => [...prev, ...uploadResults.filter(r => r.success)]);

      const successCount = uploadResults.filter(r => r.success).length;
      if (successCount > 0) {
        const systemMessage = {
          role: 'system',
          content: `✓ Uploaded ${successCount} document(s). You can now ask questions about them!`,
          timestamp: new Date()
        };
        setMessages(prev => [...prev, systemMessage]);
      }

    } catch (error) {
      console.error('Upload error:', error);
      const errorMessage = {
        role: 'system',
        content: '✗ Failed to upload documents. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleClearUploads = async () => {
    if (uploadedFiles.length === 0) return;
    
    if (!window.confirm(`Delete ${uploadedFiles.length} uploaded document(s)?`)) {
      return;
    }

    console.log('🗑️ User manually clearing uploads');

    try {
      const response = await fetch(
        `${process.env.REACT_APP_API_URL}/cleanup-session`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': process.env.REACT_APP_CHATBOT_API_KEY || ''
          },
          body: JSON.stringify({ session_id: sessionId })
        }
      );

      if (response.ok) {
        setUploadedFiles([]);
        const systemMessage = {
          role: 'system',
          content: '✓ All uploaded documents have been deleted.',
          timestamp: new Date()
        };
        setMessages(prev => [...prev, systemMessage]);
      } else {
        throw new Error('Failed to clear uploads');
      }
    } catch (error) {
      console.error('Clear error:', error);
      const errorMessage = {
        role: 'system',
        content: '✗ Failed to delete documents. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input, timestamp: new Date() };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    console.log('💬 Sending chat with session ID:', sessionId);
    console.log('📊 Uploaded files count:', uploadedFiles.length);

    try {
      const response = await sendMessage(input, sessionId);
      
      console.log('✅ Chat response received');
      console.log('🔑 Backend returned session ID:', response.session_id);
      console.log('📚 Sources count:', response.sources?.length || 0);
      
      // Don't update session ID after initial set
      if (!sessionId || sessionId === 'temp') {
        console.log('⚠️ Updating session ID from backend');
        setSessionId(response.session_id);
      } else if (response.session_id !== sessionId) {
        console.warn('⚠️ Backend returned different session ID!');
        console.warn('   Frontend:', sessionId);
        console.warn('   Backend:', response.session_id);
      }
      
      const botMessage = {
        role: 'assistant',
        content: response.response,
        sources: response.sources,
        timestamp: new Date()
      };
      
      setMessages(prev => [...prev, botMessage]);
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage = {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
        error: true
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      <div className="upload-section">
        <input
          ref={fileInputRef}
          type="file"
          id="file-upload"
          className="file-input"
          onChange={handleFileUpload}
          accept=".pdf,.jpg,.jpeg,.png,.tiff,.bmp,.docx,.txt"
          multiple
          disabled={uploading}
        />
        <label htmlFor="file-upload" className={`upload-button ${uploading ? 'uploading' : ''}`}>
          {uploading ? 'Uploading...' : 'Upload Documents'}
        </label>
        {uploadedFiles.length > 0 && (
          <>
            <span className="uploaded-count">
              {uploadedFiles.length} file(s) uploaded
            </span>
            <button 
              className="clear-button"
              onClick={handleClearUploads}
              title="Delete uploaded documents"
            >
              🗑️ Clear
            </button>
          </>
        )}
      </div>

      <div className="messages-container">
        {messages.length === 0 && (
          <div className="welcome-message">
            <h2>Welcome to YottaReal Assistant</h2>
            <p>Ask me anything about property management policies, procedures, or guidelines.</p>
            <p>I can help you with move-out procedures, lease agreements, maintenance policies, and more.</p>
          </div>
        )}
        
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role} ${message.error ? 'error' : ''}`}>
            {message.role !== 'system' && (
              <div className="message-content">
                <div className="message-header">
                  <span className="message-label">
                    {message.role === 'user' ? 'You' : 'Yotta'}
                  </span>
                  <span className="message-time">
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                <div className="message-text">{message.content}</div>
                
                {message.role === 'assistant' && !message.error && (
                  <button 
                    className="copy-button"
                    onClick={() => handleCopy(message.content, index)}
                    title="Copy message"
                  >
                    {copiedIndex === index ? '✓ Copied' : '📋 Copy'}
                  </button>
                )}
                
                {message.sources && message.sources.length > 0 && (
                  <div className="citations">
                    <div className="citations-header">
                      <strong>Sources:</strong>
                    </div>
                    <ul className="citations-list">
                      {message.sources.map((source, idx) => (
                        <li key={idx} className="citation-item">
                          <span className="citation-number">[{idx + 1}]</span>
                          <span className="citation-filename">{source.filename}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {message.role === 'system' && (
              <div className={`system-message ${message.error ? 'system-error' : 'system-success'}`}>
                {message.content}
              </div>
            )}
          </div>
        ))}
        
        {loading && (
          <div className="message assistant loading">
            <div className="message-content">
              <div className="message-timestamp">Yotta</div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <span className="typing-text">Yotta is typing...</span>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="input-form">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          disabled={loading}
          className="message-input"
        />
        <button type="submit" disabled={loading || !input.trim()} className="send-button">
          Send
        </button>
      </form>
    </div>
  );
}

export default ChatInterface;