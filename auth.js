(function(){
  'use strict';
  const body=document.body;
  const status=document.getElementById('authStatus');
  const csrf=document.querySelector('meta[name="csrf-token"]')?.content||'';
  const next=body.dataset.next||'/';
  const tabs=[...document.querySelectorAll('[data-auth-tab]')];
  const forms=[...document.querySelectorAll('[data-auth-form]')];

  function setStatus(message,type='error'){
    if(!status)return;
    status.textContent=message||'';
    status.classList.toggle('success',type==='success');
    status.hidden=!message;
  }

  function selectTab(name){
    tabs.forEach(tab=>tab.setAttribute('aria-selected',String(tab.dataset.authTab===name)));
    forms.forEach(form=>form.hidden=form.dataset.authForm!==name);
    setStatus('');
    document.querySelector(`[data-auth-form="${name}"] input`)?.focus();
  }

  tabs.forEach(tab=>tab.addEventListener('click',()=>selectTab(tab.dataset.authTab)));
  document.querySelectorAll('[data-password-toggle]').forEach(button=>button.addEventListener('click',()=>{
    const input=document.getElementById(button.dataset.passwordToggle);
    if(!input)return;
    const reveal=input.type==='password';
    input.type=reveal?'text':'password';
    button.textContent=reveal?'Hide':'Show';
    button.setAttribute('aria-label',`${reveal?'Hide':'Show'} password`);
  }));

  function markValidity(form){
    let valid=true;
    form.querySelectorAll('input[required]').forEach(input=>{
      const field=input.closest('.auth-field');
      const ok=input.checkValidity()&&Boolean(input.value.trim());
      field?.classList.toggle('invalid',!ok);
      if(!ok)valid=false;
    });
    return valid;
  }

  async function submit(form,endpoint,payload){
    if(!markValidity(form)){setStatus('Complete the highlighted fields before continuing.');return;}
    const submitButton=form.querySelector('button[type="submit"]');
    const original=submitButton.innerHTML;
    submitButton.disabled=true;
    submitButton.innerHTML='<span>Securing your session…</span><span>•••</span>';
    setStatus('');
    try{
      const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({...payload,next})});
      const data=await response.json().catch(()=>({success:false,error:'The server returned an unexpected response.'}));
      if(!response.ok||data.success===false)throw new Error(data.error||'Unable to continue.');
      if(data.pending_approval){
        form.reset();
        setStatus(data.message||'Access request submitted for administrator review.','success');
        submitButton.disabled=false;
        submitButton.innerHTML=original;
        return;
      }
      setStatus('Account verified. Opening your workspace…','success');
      window.location.assign(data.next||'/');
    }catch(error){
      setStatus(error.message||'Unable to continue.');
      submitButton.disabled=false;
      submitButton.innerHTML=original;
    }
  }

  document.getElementById('loginForm')?.addEventListener('submit',event=>{
    event.preventDefault();
    submit(event.currentTarget,'/api/auth/login',{
      email:document.getElementById('loginEmail').value.trim(),
      password:document.getElementById('loginPassword').value,
      remember:document.getElementById('loginRemember').checked
    });
  });

  document.getElementById('registerForm')?.addEventListener('submit',event=>{
    event.preventDefault();
    const password=document.getElementById('registerPassword').value;
    if(password!==document.getElementById('registerConfirm').value){
      document.getElementById('registerConfirm').closest('.auth-field')?.classList.add('invalid');
      setStatus('The two passwords do not match.');
      return;
    }
    submit(event.currentTarget,'/api/auth/register',{
      display_name:document.getElementById('registerName').value.trim(),
      email:document.getElementById('registerEmail').value.trim(),
      password,
      request_note:document.getElementById('registerNote')?.value.trim()||''
    });
  });

  document.querySelectorAll('.auth-form input').forEach(input=>input.addEventListener('input',()=>input.closest('.auth-field')?.classList.remove('invalid')));
  selectTab(tabs.some(tab=>tab.dataset.authTab===body.dataset.defaultTab)?body.dataset.defaultTab:'login');
})();
